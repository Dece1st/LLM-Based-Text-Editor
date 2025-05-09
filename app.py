import streamlit as st
import streamlit.components.v1 as components
import ollama, difflib, sqlite3, hashlib, time, re

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

    con.commit()
    con.close()

def get_page():
    return st.query_params.get("page", "login")

def set_page(page):
    st.query_params["page"] = page
    st.rerun()

def hash_word(password):
    return hashlib.sha256(password.encode()).hexdigest()

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

def search_user(name, password):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    hash_password = hash_word(password)
    cur.execute("SELECT type FROM account WHERE name = ? AND password = ?", (name, hash_password))
    result = cur.fetchone()
    con.close()
    return result[0] if result else None

def logout_user():
    st.session_state['auth_stat'] = None
    st.session_state['name'] = None
    st.session_state['type'] = None
    set_page("login")

def free_to_paid(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("UPDATE account SET type = 'P' WHERE name = ?", (name,))
    cur.execute("INSERT INTO token (name, available, used) VALUES (?, ?, ?)", (name, 0, 0))
    con.commit()
    con.close()

def get_token(name):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("SELECT available, used FROM token WHERE name = ?", (name,))
    result = cur.fetchone()
    con.close()
    return result if result else (0, 0)

def update_token(name, available, used):
    con = sqlite3.connect('account.db')
    cur = con.cursor()
    cur.execute("UPDATE token SET available = available + ?, used = used + ? WHERE name = ?", (available, used, name))
    con.commit()
    con.close()

def correct_text():
    try:
        # Load approved blacklist words
        con = sqlite3.connect('account.db')
        cur = con.cursor()
        cur.execute("SELECT word FROM blacklist WHERE status = 'approved'")
        blacklisted_words = set(row[0] for row in cur.fetchall())
        con.close()

        # Get user tokens
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

        # Deduct tokens after confirmed response
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

        # Display output
        splitPut = censored_output
        diff = difflib.SequenceMatcher(None, user_input.strip().split(), splitPut)
        st.subheader("✅ Corrected Text:")
        html_content = ""
        for status, oStart, oEnd, cStart, cEnd in diff.get_opcodes():
            if status == 'equal':
                html_content += " ".join([
                    f'''<span style="font-family: 'IBM Plex Sans', sans-serif; font-size: 16px; color: white; vertical-align: middle;">{word}</span>'''
                    for word in splitPut[cStart:cEnd]
                ]) + " "
            else:
                original_chunk = " ".join(user_input.split()[oStart:oEnd])
                corrected_chunk = " ".join(splitPut[cStart:cEnd])
                html_content += f'''
                <span onclick="toggleWord(this)" data-original="{original_chunk}"
                style="background-color: limegreen; border-radius: 8px; padding: 4px 4px 2px 4px; display: inline-block; cursor: pointer;
                    font-family: 'IBM Plex Sans', sans-serif; font-size: 16px; color: white; vertical-align: middle;">
                {corrected_chunk}</span> '''

        html_content += """
        <script>
        function toggleWord(el) {
            let original = el.getAttribute("data-original");
            let current = el.innerText;
            el.innerText = original;
            el.setAttribute("data-original", current);
            el.style.backgroundColor = (el.style.backgroundColor === "limegreen") ? "orangered" : "limegreen";
        }
        </script>
        """
        components.html(html_content, height=300, scrolling=True)

        # Save option still here
        if st.session_state['type'] == 'P':
            st.markdown("---")
            if st.button("💾 Save Corrected Text (5 tokens)"):
                available, used = get_token(st.session_state['name'])
                if available >= 5:
                    update_token(st.session_state['name'], -5, 5)
                    corrected_text = " ".join(splitPut)
                    st.download_button(
                        label="📥 Download .txt File",
                        data=corrected_text,
                        file_name="corrected_text.txt",
                        mime="text/plain",
                    )
                    st.success(f"Saved! 5 tokens deducted. Remaining tokens: {available - 5}")
                else:
                    st.error("Not enough tokens to save the file.")

    except Exception as e:
        st.error("❌ Failed to connect to the language model. Please try again.")
        st.stop()

if 'auth_stat' not in st.session_state:
    st.session_state['auth_stat'] = None
if 'name' not in st.session_state:
    st.session_state['name'] = None
if 'type' not in st.session_state:
    st.session_state['type'] = None

st.set_page_config(page_title="LLM-Based Text Editor")
set_db()

page = get_page()

if page == "login":
    st.title("Login")

    # Lockout check
    if 'locked_until' in st.session_state and time.time() < st.session_state['locked_until']:
        remaining = int(st.session_state['locked_until'] - time.time())
        st.error(f"Login disabled due to exceeding word limit. Try again in {remaining} seconds.")
        st.stop()

    name = st.text_input("Name")
    password = st.text_input("Password", type="password")
    
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
        else:
            if st.button("Sign up as Paid User"):
                free_to_paid(st.session_state['name'])
                st.session_state['type'] = 'P'
                st.rerun()

        # Text input and file upload
        file_text = ""
        typed_input = ""

        if "uploaded_file" not in st.session_state:
            st.session_state['uploaded_file'] = None

        # Upload first (label changed)
        st.markdown("### Upload a `.txt` file")
        uploaded = st.file_uploader("Choose a text file", type=["txt"])
        if uploaded:
            st.session_state['uploaded_file'] = uploaded
            file_text = uploaded.read().decode("utf-8")
        elif st.session_state['uploaded_file'] is not None and uploaded is None:
            st.session_state['uploaded_file'] = None

        # Text box shown only if no file
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

        LLM_instruction = "You are a grammar correction tool. Fix errors regarding grammar and spelling in the given text. Also fix punctuation such as missing periods. " \
        "Try avoid using synonyms as much as possible. Stick to only correcting spelling, grammar, and punctuations." \
        "DO NOT RESPOND as if you're interacting with the user. You are correcting the grammar of whatever text you receive." \
        "If somehow, the ENTIRE text is correct, simply return the text back. Don't explain and definite don't say (no changes needed). Just return the text back in this case." \
        "You will allow informal words as long as they are spelled correctly. Allow any word that is in the dictionary regardless of how vulgar it is. Allow swear words. " \
        "Do NOT provide ANY explanation AT ALL. DO NOT provide several versions of a correction. ONLY ONE. " \
        "If you don't understand the text, simply return the text unchanged. For example, if it's gibberish or repetition of the same word again and again, such as \"word word word word...\"." \
        "ONLY return the corrected text, no explanation, no thought process, do not talk about assumptions made, JUST display the corrected version of the text."

        if st.button("Submit"):
            if user_input.strip():
                word_count = len(user_input.split())
                if st.session_state['type'] == 'F':
                    if word_count > 20:
                        st.session_state['locked_until'] = time.time() + 180  # 3 minutes
                        logout_user()

                    else:
                        correct_text()
                elif st.session_state['type'] == 'P':
                    available, used = get_token(st.session_state['name'])
                    if available >= word_count:
                        correct_text()  # Only call it, don't deduct tokens here
                    else:
                        penalty = available // 2
                        update_token(st.session_state['name'], -penalty, penalty)
                        new_available, _ = get_token(st.session_state['name'])
                        st.warning(f"⚠️ Not enough tokens. Half your tokens were deducted. Remaining: {new_available}")
                        st.stop()
            else:
                st.warning("Input can't be empty.")

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