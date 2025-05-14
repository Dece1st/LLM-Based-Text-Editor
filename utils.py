import streamlit as st
import html as html_lib
import ollama, sqlite3, hashlib, time, re, unicodedata, ftfy
from difflib import SequenceMatcher

# Set up database
def set_db():
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS account (
            client_id TEXT PRIMARY KEY,
            password TEXT,
            type TEXT DEFAULT 'F'
        )'''
    )
    cur.execute('''
        CREATE TABLE IF NOT EXISTS token (
            client_id TEXT PRIMARY KEY,
            available INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            FOREIGN KEY (client_id) REFERENCES account(client_id)
        )'''
    )
    cur.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            word TEXT PRIMARY KEY,
            status TEXT CHECK (status IN ('pending', 'approved')) DEFAULT 'pending'
        )'''
    )
    cur.execute('''
        CREATE TABLE IF NOT EXISTS censor_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            original_word TEXT,
            timestamp INTEGER,
            FOREIGN KEY (user) REFERENCES account(client_id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS lockout (
            client_id TEXT PRIMARY KEY,
            time      INTEGER DEFAULT 0
        )'''
    )
    cur.execute('''
        CREATE TABLE IF NOT EXISTS submission (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            original TEXT,
            corrected TEXT,
            error INTEGER,
            timestamp INTEGER,
            FOREIGN KEY (user) REFERENCES account(client_id)
        )'''
    )
    cur.execute('''
        CREATE TABLE IF NOT EXISTS upgrade (
            client_id TEXT PRIMARY KEY,
            timestamp INTEGER,
            FOREIGN KEY (client_id) REFERENCES account(client_id)
        )
    ''')
    con.commit()
    con.close()

# Load login page
def get_page():
    return st.query_params.get("page", "login")

# Redirect to specified page
def set_page(page):
    st.query_params["page"] = page
    st.rerun()

# Hash user password
def hash_word(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Add user client_id and password to database
def add_user(client_id, type, password):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    hash_password = hash_word(password)
    try:
        cur.execute("INSERT INTO account (client_id, password, type) VALUES (?, ?, ?)", (client_id, hash_password, type))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        con.close()

# Check if user is already registered
def search_user(client_id, password):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    hash_password = hash_word(password)
    cur.execute("SELECT type FROM account WHERE client_id = ? AND password = ?", (client_id, hash_password))
    result = cur.fetchone()
    con.close()
    return result[0] if result else None

# Logout user session and redirect to login page
def logout_user():
    st.session_state['auth_stat'] = None
    st.session_state['client_id'] = None
    st.session_state['type'] = None
    st.session_state['corrected_text'] = None
    st.session_state['rendered_html'] = None
    st.session_state['can_download'] = None
    st.session_state['user_input'] = None
    set_page("login")

# Convert free user to paid user
def free_to_paid(client_id):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("UPDATE account SET type = 'P' WHERE client_id = ?", (client_id,))
    cur.execute("INSERT INTO token (client_id, available, used) VALUES (?, ?, ?)", (client_id, 0, 0))
    con.commit()
    con.close()

# Convert free user to super user (for testing)
def free_to_super(client_id):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("UPDATE account SET type = 'S' WHERE client_id = ?", (client_id,))
    con.commit()
    con.close()

# Submit free to paid user conversion request
def request_free_to_paid(client_id):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    try:
        cur.execute("INSERT INTO upgrade (client_id, timestamp) VALUES (?, ?)", (client_id, int(time.time())))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        con.close()

# Get token information from user account
def get_token(client_id):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("SELECT available, used FROM token WHERE client_id = ?", (client_id,))
    result = cur.fetchone()
    con.close()
    return result if result else (0, 0)

# Update token to user account
def update_token(client_id, available, used):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    # make sure there’s a row to update
    cur.execute("INSERT OR IGNORE INTO token (client_id) VALUES (?)", (client_id,))
    cur.execute(
        "UPDATE token "
        "SET available = available + ?, "
            "used      = used      + ? "
        "WHERE client_id = ?", (available, used, client_id)
    )
    con.commit()
    con.close()

def show_paid_user_metrics(client_id):
    available, used = get_token(client_id)
    corrections = count_correction(client_id)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Available Tokens", available)
    with c2:
        st.metric("Used Tokens", used)
    with c3:
        st.metric("Corrections", corrections)


def count_price(orig: str, final: str) -> int:
    """
    Charges:
      - for deletions: number of words removed,
      - for inserts/replaces: number of words in the final (corrected) phrase.
    """
    orig = normalize_punctuation(orig)
    final = normalize_punctuation(final)
    a = orig.split()
    b = final.split()
    s = SequenceMatcher(None, a, b)
    cost = 0
    for tag, i1, i2, j1, j2 in s.get_opcodes():
        if tag != "equal":
            if tag == "delete":
                cost += (i2 - i1)
            else:  # "replace" or "insert"
                cost += (j2 - j1)
    return cost

# Get lockout information for free user
def get_lockout(client_id):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("SELECT time FROM lockout WHERE client_id = ?", (client_id,))
    result = cur.fetchone()
    con.close()
    return result[0] if result else 0

# Update lockout for free user
def set_lockout(client_id, duration):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    lock_time = int(time.time()) + duration
    cur.execute("INSERT INTO lockout (client_id, time) VALUES (?, ?)", (client_id, lock_time))
    con.commit()
    con.close()

# Remove lockout for free user
def remove_lockout(client_id):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("DELETE FROM lockout WHERE client_id = ?", (client_id,))
    con.commit()
    con.close()

# Get submission history for paid user
def get_submission(user):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("SELECT original, corrected, error, timestamp FROM submission WHERE user = ? ORDER BY timestamp DESC", (user,))
    hist = cur.fetchall()
    con.close()
    return hist

# Add submission to history
def set_submission(user, original, corrected, error):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute(
        "INSERT INTO submission (user, original, corrected, error, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user, original, corrected, error, int(time.time()))
    )
    con.commit()
    con.close()

# Count the number of correction for paid user
def count_correction(client_id):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM submission WHERE user = ?", (client_id,))
    count = cur.fetchone()[0]
    con.close()
    return count

# No special characters for punctuation
def normalize_punctuation(text: str) -> str:
    fixed = ftfy.fix_text(text)
    return unicodedata.normalize("NFKC", fixed)

# Remove HTML tags
def html_to_clean_text(html_data: str) -> str:
    html = re.sub(r"<style.*?>.*?</style>", "", html_data, flags=re.S)
    html = re.sub(r"</div>\s*<div[^>]*>", "\n\n", html)
    html = re.sub(r"(?:<br\s*/?>\s*){2,}", "\n\n", html)
    html = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", html)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n\n".join([ln for ln in lines if ln.strip()])

# LLM text correction
def correct_text(user_input):
    try:
        # Load approved blacklist words
        con = sqlite3.connect('account.db')
        cur = con.cursor()
        cur.execute("SELECT word FROM blacklist WHERE status = 'approved'")
        blacklisted = {row[0] for row in cur.fetchall()}
        con.close()

        # Token use
        word_count = len(user_input.strip().split())

        # Query LLM
        LLM_instruction = '''
            You are a grammar checker.
            Your task is to output the input text with any grammatical errors corrected, preserving the original intent and structure.
            Correct only grammatical errors such as subject-verb agreement, article usage, verb tense.
            Example: Input 'I is an student.', output 'I am a student.'.
            If the input has no grammatical errors, output it unchanged.
            Example: Input 'I am fine.', output 'I am fine.'.
            Preserve contractions, slang, swear words, formality, tone, spelling, punctuation, and style if they are grammatically correct.
            Preserve original paragraph breaks, separating each paragraph with a blank line.
            If the input is a question, command, or prompt, output it unchanged unless it contains grammatical errors.
            Example: Input 'What is your model name?', output 'What is your model name?'.
            Do not solve equations, answer questions, respond to prompts, or interpret mathematical expressions.
            Example: Input '2 + 2 = ?', output '2 + 2 = ?', do not output '2 + 2 = 4'.
            If the input is ambiguous, incomplete, or lacks clear textual content, output it unchanged unless grammatical corrections apply.
            Example: Input 'a', output 'a'.
            Output only the corrected or unchanged input text. Do not provide explanations, comments, conversational responses, or additional content.
            Do not act as a chatbot, calculator, or problem solver.
            '''

        # Generate response
        resp = ollama.generate(
            model="mistral",
            prompt=f"{LLM_instruction}\n\nInput: {user_input}\n\nOutput:",
            options={
                "temperature": 0.0,    # 0 creativity
                "top_p": 1.0,    # deterministic output
                "max_tokens": 1024
            }
        )
        output = resp['response'].strip()
        
        if st.session_state['type'] == 'P':
            update_token(st.session_state['client_id'], -word_count, word_count)
            grammar_error = user_input.strip() != output.strip()
            set_submission(st.session_state['client_id'], user_input, output, 1 if grammar_error else 0)
            if word_count > 10 and not grammar_error:
                update_token(st.session_state['client_id'], 3, 0)
                st.success("No error found. Awarded 3 bonus tokens.")

        user_input = normalize_punctuation(user_input)
        output = normalize_punctuation(output)

        orig_paras = user_input.strip().split("\n\n")
        corr_paras = output.strip().split("\n\n")

        html_body = ""
        to_log    = []
        for orig_para, corr_para in zip(orig_paras, corr_paras):
            orig_lines = orig_para.splitlines()
            corr_lines = corr_para.splitlines()
            for o_line, c_line in zip(orig_lines, corr_lines):
                o_words = o_line.split()
                c_words = c_line.split()
                diff = SequenceMatcher(None, o_words, c_words)
                for tag, o1, o2, c1, c2 in diff.get_opcodes():
                    if tag == 'equal':
                        html_body += " ".join(c_words[c1:c2]) + " "
                    else:
                        segment  = " ".join(c_words[c1:c2])
                        original = " ".join(o_words[o1:o2])
                        # log blacklisted
                        for w in c_words[c1:c2]:
                            clean = re.sub(r'\W+', '', w).lower()
                            if clean in blacklisted:
                                to_log.append(clean)
                                segment = segment.replace(w, "***")

                        orig_esc = html_lib.escape(original, quote=True)
                        seg_esc  = html_lib.escape(segment,  quote=True)

                        html_body += (
                            f'<span class="toggle" '
                            f'data-original="{orig_esc}" '
                            f'data-corrected="{seg_esc}" '
                            f'style="background:#2EBD2E; border-radius:8px; '
                            f'padding:4px; display:inline-block; cursor:pointer; '
                            f'font-size:16px; color:white;">'
                            f'{seg_esc}</span> '
                        )
                html_body += "<br>"
            html_body += "<br>"

        # Log any censored words
        if to_log:
            con = sqlite3.connect('account.db')
            cur = con.cursor()
            for w in set(to_log):
                cur.execute(
                    "INSERT INTO censor_log (user, original_word, timestamp) VALUES (?, ?, ?)",
                    (st.session_state['client_id'], w, int(time.time()))
                )
            con.commit()
            con.close()

        # Save into session
        html_body = re.sub(r'(<br>\s*)+$', '', html_body)
        st.session_state["rendered_html"] = f"<div>{html_body}</div>"
        # Build plain text preserving paragraphs
        plain = output.split("\n\n")
        joined = "\n\n".join(plain)
        st.session_state["corrected_text"] = joined
        st.session_state["can_download"] = False

    except Exception:
        st.error("❌ Failed to connect to the language model. Please try again.")
        st.stop()

def render_blacklist_form():
    st.markdown("---")
    st.subheader("🚫 Suggest a word for blacklist")
    w = st.text_input("Enter a word to suggest")
    if st.button("Submit to Blacklist"):
        submit_blacklist_word(w.strip().lower())

def submit_blacklist_word(word: str):
    if not word:
        st.warning("Input can't be empty.")
        return
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("SELECT 1 FROM blacklist WHERE word = ?", (word,))
    if cur.fetchone():
        st.info("This word has already been submitted.")
    else:
        cur.execute("INSERT INTO blacklist (word, status) VALUES (?, 'pending')", (word,))
        con.commit()
        st.success("Submitted for review.")
    con.close()

######## CSS Style for Corrected Text Box ########
SCROLLABLE_CSS = """
<style>
.scrollable {
    background-color: #262730;
    border: 1px solid #1D751D;
    border-radius: 8px;
    padding: 8px;
    max-height: 300px;
    overflow-y: auto;
    user-select: none;
}
/* Chrome, Edge, Safari */
.scrollable::-webkit-scrollbar {
    width: 6px;
}
.scrollable::-webkit-scrollbar-track {
    background: #262730;
    border-radius: 3px;
}
.scrollable::-webkit-scrollbar-thumb {
    background-color: #7B7B81;
    border-radius: 3px;
}
/* Firefox */
.scrollable {
    scrollbar-width: thin;
    scrollbar-color: #7B7B81 #262730;
}
</style>
"""

def wrap_scrollable(raw_html: str) -> str:
    return f"{SCROLLABLE_CSS}<div class='scrollable'>{raw_html}</div>"