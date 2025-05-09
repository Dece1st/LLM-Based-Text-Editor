import streamlit as st
import streamlit.components.v1 as components
import ollama, difflib, sqlite3, hashlib, time, re

st.set_page_config(page_title="LLM-Based Text Editor")

# ✅ Initialize session state keys in one loop
for key in ['auth_stat', 'name', 'type']:
    st.session_state.setdefault(key, None)

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
    set_page("login")

# Convert free user to paid user
def free_to_paid(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("UPDATE account SET type = 'P' WHERE name = ?", (name,))
    cur.execute("INSERT INTO token (name, available, used) VALUES (?, ?, ?)", (name, 0, 0))
    con.commit()
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

@st.fragment
def render_download_button():
    st.download_button(
        label="📥 Download .txt File",
        data=st.session_state["corrected_text"],
        file_name="corrected_text.txt",
        mime="text/plain"
    )

# Get lockout information for free user
def get_lockout(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("SELECT time FROM lockout WHERE name = ?", (name,))
    result = cur.fetchone()
    return result[0] if result else 0
    con.close()

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
def correct_text():
    try:
        user_input = st.session_state["user_input"]

        # Load approved blacklist words
        con = sqlite3.connect('account.db')
        cur = con.cursor()
        cur.execute("SELECT word FROM blacklist WHERE status = 'approved'")
        blacklisted_words = set(row[0] for row in cur.fetchall())
        con.close()

        # Get token usage
        available, used = get_token(st.session_state['name'])
        word_count = len(user_input.strip().split())

        # Query LLM
        response = ollama.chat(
            model="mistral",
            messages=[
                {"role": "system", "content": LLM_instruction},
                {"role": "user", "content": user_input}
            ]
        )
        output = response['message']['content']
        words = output.split()

        # Deduct tokens
        update_token(st.session_state['name'], -word_count, word_count)

        # Censoring
        censored_output, to_log = [], []
        for word in words:
            clean = re.sub(r'\W+', '', word).lower()
            if clean in blacklisted_words:
                to_log.append(clean)
                censored_output.append("***")
            else:
                censored_output.append(word)

        if to_log:
            con = sqlite3.connect('account.db')
            cur = con.cursor()
            for w in to_log:
                cur.execute("INSERT INTO censor_log (user, original_word, timestamp) VALUES (?, ?, ?)",
                            (st.session_state['name'], w, int(time.time())))
            con.commit()
            con.close()

        # Save initial version for comparison
        st.session_state["corrected_text"] = " ".join(censored_output)

        # Build HTML with toggle + locking logic
        diff = difflib.SequenceMatcher(None, user_input.strip().split(), censored_output)
        html_content = """
        <script>
        let editingLocked = false;

        function toggleWord(el) {
            if (editingLocked) return;
            let original = el.getAttribute("data-original");
            let current = el.innerText;
            el.innerText = original;
            el.setAttribute("data-original", current);
            el.style.backgroundColor = (el.style.backgroundColor === "limegreen") ? "orangered" : "limegreen";
        }

        function prepareDownloadText() {
            const spans = Array.from(document.querySelectorAll("span[data-original]"));
            const collected = spans.map(s => s.innerText).join(" ");
            const input = window.parent.document.querySelector('input[data-baseweb="input"]');
            if (input) {
                input.value = collected;
                input.dispatchEvent(new Event("input", { bubbles: true }));
            }
            editingLocked = true;
        }
        </script>
        <div>
        """

        for status, oStart, oEnd, cStart, cEnd in diff.get_opcodes():
            if status == 'equal':
                html_content += " ".join([
                    f"<span style='font-size: 16px; color: white;'>{word}</span>"
                    for word in censored_output[cStart:cEnd]
                ]) + " "
            else:
                original = " ".join(user_input.split()[oStart:oEnd])
                corrected = " ".join(censored_output[cStart:cEnd])
                html_content += f"""
                <span onclick="toggleWord(this)" data-original="{original}"
                style="background-color: limegreen; border-radius: 8px; padding: 4px; display: inline-block; cursor: pointer;
                font-size: 16px; color: white;">
                {corrected}</span> """

        html_content += "</div><script>window.renderedOnce = true;</script>"
        st.session_state["rendered_html"] = html_content
        st.session_state["can_download"] = False  # Reset flag
    except Exception:
        st.error("❌ Failed to connect to the language model. Please try again.")
        st.stop()

set_db()

page = get_page()

if page == "login":
    st.title("Login")
    name = st.text_input("Name")
    password = st.text_input("Password", type="password")

    # Lockout check
    lock_time = get_lockout(name)
    if lock_time > int(time.time()):
        remaining = lock_time - int(time.time())
        st.error(f"Account locked due to exceeding word limit. Try again in {remaining} seconds.")
        st.stop()
    
    if st.button("Login"):
        type = search_user(name, password)
        if type:
            st.session_state['auth_stat'] = True
            st.session_state['name'] = name
            st.session_state['type'] = type
            set_page("main")
        else:
            st.session_state['auth_stat'] = False
    
    if st.button("Sign Up"):
        set_page("signup")
    
    if st.session_state['auth_stat'] == False:
        st.error("Incorrect name/password")
    elif st.session_state['auth_stat'] is None:
        st.warning("Please enter name and password")

elif page == "signup":
    st.title("Sign Up")
    name = st.text_input("Name")
    password = st.text_input("Password", type="password")
    
    if st.button("Sign Up"):
        if name and password:
            if add_user(name, 'F', password):
                set_page("login")
            else:
                st.error("Name already exists")
        else:
            st.error("Please fill in all fields")
    
    if st.button("Login"):
        set_page("login")

elif page == "moderation":
    if st.session_state['type'] != 'S':
        st.error("Access denied.")
        set_page("main")
    else:
        st.title("🛠️ Moderation Panel")
        st.subheader("Pending Blacklist Submissions")

        con = sqlite3.connect('account.db')
        cur = con.cursor()
        cur.execute("SELECT word FROM blacklist WHERE status = 'pending'")
        pending_words = cur.fetchall()

        if not pending_words:
            st.info("No pending words.")
        else:
            for word_tuple in pending_words:
                word = word_tuple[0]
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"🔸 {word}")
                with col2:
                    if st.button("✅ Approve", key=f"approve_{word}"):
                        cur.execute("UPDATE blacklist SET status = 'approved' WHERE word = ?", (word,))
                        con.commit()
                        st.rerun()
                    if st.button("❌ Reject", key=f"reject_{word}"):
                        cur.execute("DELETE FROM blacklist WHERE word = ?", (word,))
                        con.commit()
                        st.rerun()
        con.close()

elif page == "logs":
    if st.session_state['type'] != 'S':
        st.error("Access denied.")
        set_page("main")
    else:
        st.title("📜 Censor Logs")
        con = sqlite3.connect('account.db')
        cur = con.cursor()
        cur.execute("SELECT user, original_word, timestamp FROM censor_log ORDER BY timestamp DESC")
        logs = cur.fetchall()
        con.close()

        if not logs:
            st.info("No censored words recorded.")
        else:
            for user, word, ts in logs:
                ts_fmt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
                st.write(f"🔸 `{word}` was submitted by **{user}** at `{ts_fmt}`")

elif page == "main":
    if not st.session_state['auth_stat']:
        set_page("login")
    else:
        st.title("📝 LLM-Based Text Editor")
        if st.session_state['type'] == 'S':
            if st.button("Go to Moderation Panel"):
                set_page("moderation")

        st.write(f"Hello, {st.session_state['name']}!")

        if st.session_state['type'] == 'P':
            available, used = get_token(st.session_state['name'])
            st.write(f"Available Tokens: {available}")
            st.write(f"Used Tokens: {used}")
            token_input = st.number_input("Enter Tokens", min_value=1, step=1)
            if st.button("Add Tokens"):
                update_token(st.session_state['name'], token_input, 0)
                st.rerun()
        elif st.session_state['type'] == 'F':
            is_locked = get_lockout(st.session_state['name'])
            if is_locked:
                remove_lockout(st.session_state['name'])
            if st.button("Sign up as Paid User"):
                free_to_paid(st.session_state['name'])
                st.session_state['type'] = 'P'
                st.rerun()

        file_text = ""
        typed_input = ""

        if "uploaded_file" not in st.session_state:
            st.session_state['uploaded_file'] = None

        st.markdown("### Upload a `.txt` file")
        uploaded = st.file_uploader("Choose a text file", type=["txt"])
        if uploaded:
            st.session_state['uploaded_file'] = uploaded
            file_text = uploaded.read().decode("utf-8")
        elif st.session_state['uploaded_file'] is not None and uploaded is None:
            st.session_state['uploaded_file'] = None

        if st.session_state['uploaded_file'] is None:
            st.markdown("### Or input your text:")
            typed_input = st.text_area(label="Your text:", placeholder="Start typing here...")

        user_input = typed_input.strip() or file_text.strip()

        word_count = len(user_input.split())
        if st.session_state['type'] == 'F' and word_count > 20:
            st.markdown(f"<span style='color:red;'>Word count: {word_count} (Limit: 20. Submitting will result in a 3 minute timeout.)</span>", unsafe_allow_html=True)
        elif st.session_state['type'] == 'P':
            available, _ = get_token(st.session_state['name'])
            if word_count > available:
                st.markdown(f"<span style='color:red;'>Word count: {word_count} (Exceeds available tokens: {available}. Submitting will cut your tokens in half.)</span>", unsafe_allow_html=True)
            else:
                st.write(f"Word count: {word_count}")
        else:
            st.write(f"Word count: {word_count}")

        LLM_instruction = (
            "Correct grammar, spelling, and punctuation only. "
            "Do not explain, justify, or respond conversationally. "
            "If text is already correct or unreadable, return it unchanged. "
            "Allow slang and swear words if spelled correctly. "
            "Output only the corrected text—no extra comments or options."
        )

        if st.button("Submit"):
            if user_input.strip():
                word_count = len(user_input.split())
                instruction_like = (
                    re.search(r"(correct grammar|output only|do not explain|return it unchanged|fix (spelling|punctuation))", user_input.lower())
                    and word_count < 25
                )
                if instruction_like:
                    st.warning("⚠️ Your input looks like an instruction. If you're trying to correct a real sentence, rephrase it to avoid triggering unintended behavior.")
                else:
                    if st.session_state['type'] == 'F':
                        if word_count > 20:
                            set_lockout(st.session_state['name'], 180)
                            logout_user()
                        else:
                            st.session_state["user_input"] = user_input
                            correct_text()
                    elif st.session_state['type'] == 'P':
                        available, used = get_token(st.session_state['name'])
                        if available >= word_count:
                            st.session_state["user_input"] = user_input
                            correct_text()
                        else:
                            penalty = available // 2
                            update_token(st.session_state['name'], -penalty, penalty)
                            new_available, _ = get_token(st.session_state['name'])
                            st.warning(f"⚠️ Not enough tokens. Half your tokens were deducted. Remaining: {new_available}")
                            st.stop()
            else:
                st.warning("Input can't be empty.")

        if st.session_state.get("corrected_text"):
            st.subheader("✅ Corrected Text:")
            components.html(st.session_state["rendered_html"], height=300, scrolling=True)

            # Hidden input (true HTML hidden field, not Streamlit input)
            st.markdown('<input type="hidden" id="hidden_download_text" name="hidden_download_text">', unsafe_allow_html=True)

        if not st.session_state.get("can_download"):
            st.markdown("---")
            st.markdown("⚠️ After pressing this, edits will be locked.", unsafe_allow_html=True)
            if st.button("💾 Prepare for Download (5 tokens)"):
                available, _ = get_token(st.session_state['name'])
                if available >= 5:
                    update_token(st.session_state['name'], -5, 5)
                    st.session_state["can_download"] = True
                    st.success(f"File ready! 5 tokens deducted. Remaining tokens: {available - 5}")
                else:
                    st.error("Not enough tokens to save the file.")

        if st.session_state.get("can_download"):
            st.download_button(
                "📥 Download .txt File",
                st.session_state["corrected_text"],
                file_name="corrected_text.txt",
                mime="text/plain"
            )

        if st.session_state['type'] != 'S':
            st.markdown("---")
            st.subheader("🔒 Suggest a word for blacklist")
            blacklist_word = st.text_input("Enter a word to suggest")

            if st.button("Submit to Blacklist") and blacklist_word.strip():
                word = blacklist_word.strip().lower()
                con = sqlite3.connect('account.db')
                cur = con.cursor()
                cur.execute("SELECT * FROM blacklist WHERE word = ?", (word,))
                exists = cur.fetchone()
                if exists:
                    st.info("This word has already been submitted.")
                else:
                    cur.execute("INSERT INTO blacklist (word, status) VALUES (?, 'pending')", (word,))
                    con.commit()
                    st.success("Submitted for review.")
                con.close()

            if st.button("View Logs"):
                set_page("logs")

        if st.button("Logout"):
            logout_user()