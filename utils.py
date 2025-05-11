import streamlit as st
import ollama, difflib, sqlite3, hashlib, time, re

# Set up database
def set_db():
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS account (
            name TEXT PRIMARY KEY,
            password TEXT,
            type TEXT DEFAULT 'F'
        )'''
    )
    cur.execute('''
        CREATE TABLE IF NOT EXISTS token (
            name TEXT PRIMARY KEY,
            available INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            FOREIGN KEY (name) REFERENCES account(name)
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
            FOREIGN KEY (user) REFERENCES account(name)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS lockout (
            name TEXT PRIMARY KEY,
            time INTEGER DEFAULT 0,
            FOREIGN KEY (name) REFERENCES account(name)
        )'''
    )
    cur.execute('''
        CREATE TABLE IF NOT EXISTS upgrade (
            name TEXT PRIMARY KEY,
            timestamp INTEGER,
            FOREIGN KEY (name) REFERENCES account(name)
        )'''
    )
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

# Add user name and password to database
def add_user(name, type, password):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    hash_password = hash_word(password)
    try:
        cur.execute("INSERT INTO account (name, password, type) VALUES (?, ?, ?)", (name, hash_password, type))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        con.close()

# Check if user is already registered
def search_user(name, password):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    hash_password = hash_word(password)
    cur.execute("SELECT type FROM account WHERE name = ? AND password = ?", (name, hash_password))
    result = cur.fetchone()
    con.close()
    return result[0] if result else None

# Logout user session and redirect to login page
def logout_user():
    st.session_state['auth_stat'] = None
    st.session_state['name'] = None
    st.session_state['type'] = None
    st.session_state['corrected_text'] = None
    st.session_state['rendered_html'] = None
    st.session_state['can_download'] = None
    st.session_state['user_input'] = None
    set_page("login")

# Convert free user to paid user
def free_to_paid(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("UPDATE account SET type = 'P' WHERE name = ?", (name,))
    cur.execute("INSERT INTO token (name, available, used) VALUES (?, ?, ?)", (name, 0, 0))
    con.commit()
    con.close()

# Convert free user to super user (for testing)
def free_to_super(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("UPDATE account SET type = 'S' WHERE name = ?", (name,))
    con.commit()
    con.close()

# Submit free to paid user conversion request
def request_free_to_paid(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    try:
        cur.execute("INSERT INTO upgrade (name, timestamp) VALUES (?, ?)", (name, int(time.time())))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        con.close()

# Get token information from user account
def get_token(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("SELECT available, used FROM token WHERE name = ?", (name,))
    result = cur.fetchone()
    con.close()
    return result if result else (0, 0)

# Update token to user account
def update_token(name, available, used):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("UPDATE token SET available = available + ?, used = used + ? WHERE name = ?", (available, used, name))
    con.commit()
    con.close()

# Get lockout information for free user
def get_lockout(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("SELECT time FROM lockout WHERE name = ?", (name,))
    result = cur.fetchone()
    con.close()
    return result[0] if result else 0

# Update lockout for free user
def set_lockout(name, duration):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    lock_time = int(time.time()) + duration
    cur.execute("INSERT INTO lockout (name, time) VALUES (?, ?)", (name, lock_time))
    con.commit()
    con.close()

# Remove lockout for free user
def remove_lockout(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("DELETE FROM lockout WHERE name = ?", (name,))
    con.commit()
    con.close()

# LLM text correction
def correct_text(user_input):
    try:
        # Load approved blacklist words
        con = sqlite3.connect('account.db')
        cur = con.cursor()
        cur.execute("SELECT word FROM blacklist WHERE status = 'approved'")
        blacklisted_words = {row[0] for row in cur.fetchall()}
        con.close()

        # Token use
        available, used = get_token(st.session_state['name'])
        word_count = len(user_input.strip().split())

        # Query LLM
        LLM_instruction = (
            "Correct grammar, spelling, and punctuation only. "
            "Do not explain, justify, or respond conversationally. "
            "If text is already correct or unreadable, return it unchanged. "
            "Allow slang and swear words if spelled correctly. "
            "Output only the corrected text—no extra comments or options."
            "Please preserve the original paragraph breaks. In your output, separate each paragraph with a blank line."
        )
        
        response = ollama.chat(
            model="mistral",
            messages=[
                {"role": "system", "content": LLM_instruction},
                {"role": "user", "content": user_input}
            ]
        )
        output = response['message']['content']
        words = output.split()

        # Deduct tokens for the LLM pass
        update_token(st.session_state['name'], -word_count, word_count)

        # Censoring
        censored_output = []
        to_log = []
        for w in words:
            clean = re.sub(r'\W+', '', w).lower()
            if clean in blacklisted_words:
                to_log.append(clean)
                censored_output.append("***")
            else:
                censored_output.append(w)

        # Log censored words
        if to_log:
            con = sqlite3.connect('account.db')
            cur = con.cursor()
            for w in to_log:
                cur.execute(
                    "INSERT INTO censor_log (user, original_word, timestamp) VALUES (?, ?, ?)",
                    (st.session_state['name'], w, int(time.time()))
                )
            con.commit()
            con.close()

        # Save raw corrected text
        st.session_state["corrected_text"] = " ".join(censored_output)

        # Build HTML for the custom component
        diff = difflib.SequenceMatcher(
            None,
            user_input.strip().split(),
            censored_output
        )
        html_content = "<div>"
        for tag, o1, o2, c1, c2 in diff.get_opcodes():
            if tag == 'equal':
                for w in censored_output[c1:c2]:
                    html_content += f"{w} "
            else:
                original = " ".join(user_input.strip().split()[o1:o2])
                corrected = " ".join(censored_output[c1:c2])
                html_content += (
                    f"<span class=\"toggle\" "
                    f"data-original=\"{original}\" "
                    f"data-corrected=\"{corrected}\" "
                    f"style=\"background:limegreen; border-radius:8px; "
                    f"padding:4px; display:inline-block; cursor:pointer; "
                    f"font-size:16px; color:white;\">"
                    f"{corrected}</span> "
                )
        html_content += "</div>"

        # Store for rendering
        st.session_state["rendered_html"] = html_content
        st.session_state["can_download"] = False

    except Exception:
        st.error("❌ Failed to connect to the language model. Please try again.")
        st.stop()