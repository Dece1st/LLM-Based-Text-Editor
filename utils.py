import streamlit as st
import html as html_lib
import ollama, difflib, sqlite3, hashlib, time, re, unicodedata

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

_PUNCT_MAP = {
    # quotes
    '\u2018': "'",  # left single quotation mark
    '\u2019': "'",  # right single quotation mark
    '\u201C': '"',  # left double quotation mark
    '\u201D': '"',  # right double quotation mark
    '\u00AB': '"',  # left-pointing guillemet
    '\u00BB': '"',  # right-pointing guillemet

    # dashes
    '\u2013': '-',  # en dash
    '\u2014': '-',  # em dash

    # ellipsis
    '\u2026': '...', 

    # spaces
    '\u00A0': ' ',  # non-breaking space

    # daggers, bullets, etc (optional)
    '\u2022': '*',  # bullet
    '\u2020': '+',  # dagger
}
_PUNCT_RE = re.compile('|'.join(re.escape(c) for c in _PUNCT_MAP))

def normalize_punctuation(text: str) -> str:
    """
    Replace common Unicode punctuation with ASCII equivalents, then
    apply Unicode compatibility normalization (NFKC) for any others.
    """
    # first, map our table
    text = _PUNCT_RE.sub(lambda m: _PUNCT_MAP[m.group(0)], text)
    # then normalize compatibility chars (like ﬁ → fi)
    text = unicodedata.normalize('NFKC', text)
    return text

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
        available, used = get_token(st.session_state['client_id'])
        word_count = len(user_input.strip().split())

        # Query LLM
        LLM_instruction = (
            "Correct grammar, spelling, and punctuation only. "
            "Do not explain, justify, or respond conversationally. "
            "If text is already correct or unreadable, return it unchanged. "
            "Allow slang and swear words if spelled correctly. "
            "Output only the corrected text—no extra comments or options. "
            "Please preserve the original paragraph breaks. "
            "In your output, separate each paragraph with a blank line."
        )
        resp = ollama.chat(
            model="mistral",
            messages=[
                {"role": "system", "content": LLM_instruction},
                {"role": "user",   "content": user_input}
            ]
        )
        output = resp['message']['content']
        
        if st.session_state['type'] == 'P':
            # Deduct tokens for submission
            update_token(st.session_state['client_id'], -word_count, word_count)
            grammar_error = user_input.strip() != output.strip()
            # Save submission to history
            set_submission(st.session_state['client_id'], user_input, output, 1 if grammar_error else 0)
            # Award bonus tokens for submission with no error
            if word_count > 10 and not grammar_error:
                update_token(st.session_state['client_id'], 3, 0)
                st.success("No error found. Awarded 3 bonus tokens.")

        # Prepare for diffing
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
                diff = difflib.SequenceMatcher(None, o_words, c_words)
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