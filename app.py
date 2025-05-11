from streamlit_html_viewer.streamlit_html_viewer import streamlit_html_viewer as html_viewer
import streamlit as st
from utils import *

st.set_page_config(page_title="LLM-Based Text Editor")

# Initialize session state keys
for key in ['auth_stat', 'name', 'type', 'corrected_text', 'rendered_html', 'can_download', 'user_input']:
    st.session_state.setdefault(key, None)

@st.fragment
def render_download_button():
    st.download_button(
        label="📥 Download .txt File",
        data=st.session_state["corrected_text"],
        file_name="corrected_text.txt",
        mime="text/plain"
    )

set_db()
page = get_page()

if page == "login":
    st.title("Login")

    with st.form("login_fom"):
        name = st.text_input("Name")
        password = st.text_input("Password", type="password")

        submitted_login = st.form_submit_button("Login")
        submitted_signup = st.form_submit_button("Sign Up")

    # Lockout check
    lock_time = get_lockout(name)
    if lock_time > int(time.time()):
        remaining = lock_time - int(time.time())
        st.error(f"Account locked due to exceeding word limit. Try again in {remaining} seconds.")
        st.stop()
    
    if submitted_login:
        type = search_user(name, password)
        if type:
            st.session_state['auth_stat'] = True
            st.session_state['name'] = name
            st.session_state['type'] = type
            set_page("main")
        else:
            st.session_state['auth_stat'] = False
            st.error("Incorrect username or password")
    
    if submitted_signup:
        set_page("signup")
    
    if st.session_state['auth_stat'] is None:
        st.warning("Please enter name and password")

elif page == "signup":
    st.title("Sign Up")

    # Signup form
    with st.form("signup_form"):
        name = st.text_input("Name")
        password = st.text_input("Password", type="password")

        submitted_signup = st.form_submit_button("Sign Up")
        submitted_login = st.form_submit_button("Login")

    if submitted_signup:
        if name and password:
            if add_user(name, 'F', password):
                st.success("Signup successful! Redirecting to login...")
                set_page("login")
            else:
                st.error("Name already exists")
        else:
            st.error("Please fill in all fields")

    if submitted_login:
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
        
        st.subheader("Pending Paid User Requests")
        cur.execute("SELECT name, timestamp FROM upgrade")
        request = cur.fetchall()
        if request:
            for name, timestamp in request:
                ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"🔸 User: {name} (Requested at: {ts})")
                with col2:
                    if st.button("✅ Approve", key=f"approve_{name}"):
                        free_to_paid(name)
                        cur.execute("DELETE FROM upgrade WHERE name = ?", (name,))
                        con.commit()
                        st.rerun()
                    if st.button("❌ Decline", key=f"decline_{name}"):
                        cur.execute("DELETE FROM upgrade WHERE name = ?", (name,))
                        con.commit()
                        st.rerun()
        else:
            st.info("No pending requests.")
        con.close()
        
        if st.button("Back to Main Page"):
            set_page("main")
        
        if st.button("Logout"):
            logout_user()

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
        
        if st.button("Back to Main Page"):
            set_page("main")
        
        if st.button("Logout"):
            logout_user()

elif page == "history":
    if st.session_state['type'] != 'P':
        st.error("Access denied.")
        set_page("main")
    else:
        st.title("📜 Submission History")
        history = get_submission(st.session_state['name'])
        
        if not history:
            st.info("No submission recorded.")
        else:
            st.subheader("Past Submissions")
            for original, corrected, error, timestamp in history:
                ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
                with st.expander(f"Submitted at {ts} ({'Error' if error else 'No Error'})"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("Original Text")
                        st.text_area("", original, height=150, disabled=True, key=f"original_{timestamp}")
                    with col2:
                        st.markdown("Corrected Text")
                        st.text_area("", corrected, height=150, disabled=True, key=f"corrected_{timestamp}")
        
        if st.button("Back to Main Page"):
            set_page("main")
        
        if st.button("Logout"):
            logout_user()

elif page == "main":
    if not st.session_state['auth_stat']:
        set_page("login")
    else:
        st.title("📝 LLM-Based Text Editor")
        if st.session_state['type'] == 'S':
            if st.button("Go to Moderation Panel"):
                set_page("moderation")
            
            if st.button("View Logs"):
                set_page("logs")

        st.write(f"Hello, {st.session_state['name']}!")

        if st.session_state['type'] == 'P':
            available, used = get_token(st.session_state['name'])
            st.write(f"Available Tokens: {available}")
            st.write(f"Used Tokens: {used}")
            token_input = st.number_input("Enter Tokens", min_value=1, step=1)
            
            if st.button("Add Tokens"):
                update_token(st.session_state['name'], token_input, 0)
                st.rerun()
            
            if st.button("View Submission History"):
                set_page("history")
        
        elif st.session_state['type'] == 'F':
            is_locked = get_lockout(st.session_state['name'])
            if is_locked:
                remove_lockout(st.session_state['name'])
            
            if st.button("Sign up as Paid User"):
                if request_free_to_paid(st.session_state['name']):
                    st.success("Request submitted. Awaiting super user approval.")
                else:
                    st.info("You have already submitted a request.")
            
            if st.button("Test as Super User"):
                free_to_super(st.session_state['name'])
                st.session_state['type'] = 'S'
                st.rerun()

        file_text = ""
        typed_input = ""

        if "uploaded_file" not in st.session_state:
            st.session_state['uploaded_file'] = None

        if st.session_state['type'] != 'S':
            st.markdown("### Upload a `.txt` file")
            uploaded = st.file_uploader("Choose a text file", type=["txt"])
            if uploaded:
                st.session_state['uploaded_file'] = uploaded
                file_text = uploaded.read().decode("utf-8")
            elif st.session_state['uploaded_file'] is not None and uploaded is None:
                st.session_state['uploaded_file'] = None

            if st.session_state['uploaded_file'] is None:
                st.markdown("### Or input your text:")
                typed_input = st.text_area(label="Your text:", placeholder="Start typing here...", height=170)

            user_input = (typed_input or file_text).rstrip()

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
                                correct_text(user_input)
                        elif st.session_state['type'] == 'P':
                            available, used = get_token(st.session_state['name'])
                            if available >= word_count:
                                st.session_state["user_input"] = user_input
                                correct_text(user_input)
                            else:
                                penalty = available // 2
                                update_token(st.session_state['name'], -penalty, penalty)
                                new_available, _ = get_token(st.session_state['name'])
                                st.warning(f"⚠️ Not enough tokens. Half your tokens were deducted. Remaining: {new_available}")
                                st.stop()
                else:
                    st.warning("Input can't be empty.")

            if st.session_state.get("rendered_html") and not st.session_state.get("can_download"):
                st.subheader("✅ Corrected Text")
                edited = html_viewer(
                    html=st.session_state["rendered_html"],
                    height=300
                )
                if edited is not None:
                    st.session_state["corrected_text"] = edited

            if st.session_state['type'] == 'P':
                if st.session_state.get("corrected_text") and not st.session_state.get("can_download"):
                    st.markdown("---")
                    st.markdown(
                        "⚠️ After pressing this, edits will be locked.",
                        unsafe_allow_html=True
                    )
                    if st.button("💾 Prepare for Download (5 tokens)"):
                        available, _ = get_token(st.session_state['name'])
                        if available >= 5:
                            update_token(st.session_state['name'], -5, 5)
                            st.session_state["can_download"] = True
                            st.success(f"File ready! 5 tokens deducted. Remaining: {available - 5}")
                            st.rerun()
                        else:
                            st.error("Not enough tokens to save the file.")

                if st.session_state.get("can_download"):
                    st.markdown("### 📄 Preview of Approved Edits")
                    html_data = st.session_state["corrected_text"]
                    html_data = html_data.replace("</div><div", "</div>\n\n<div")
                    text_only = re.sub(r"<[^>]+>", "", html_data)
                    lines = [ " ".join(line.split()) for line in text_only.splitlines() ]
                    clean_text = "\n\n".join([ln for ln in lines if ln.strip()])
                    st.text_area("", clean_text, height=200, disabled=True)
                    st.download_button(
                        label="📥 Download edits",
                        data=clean_text,
                        file_name="corrected_text.txt",
                        mime="text/plain",
                    )

            st.markdown("---")
            st.subheader("🔒 Suggest a word for blacklist")
            blacklist_word = st.text_input("Enter a word to suggest")

            if st.button("Submit to Blacklist"):
                if blacklist_word.strip():
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
                else:
                    st.warning("Input can't be empty.")

        if st.button("Logout"):
            logout_user()