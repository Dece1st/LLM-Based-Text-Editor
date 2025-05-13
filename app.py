from streamlit_html_viewer.streamlit_html_viewer import streamlit_html_viewer as html_viewer
from utils import *
import streamlit as st
import os

st.set_page_config(page_title="LLM-Based Text Editor")

# Initialize session state keys
for key in ['auth_stat', 'name', 'type', 'client_id', 'corrected_text', 'rendered_html', 'can_download', 'user_input']:
    st.session_state.setdefault(key, None)

ip = st.context.ip_address
if not ip:
    ip = st.query_params.get("client_ip", [None])[0]
client_id = ip or ""
st.session_state['client_id'] = client_id

st.markdown(
    """
    <style>
      label[data-testid="stWidgetLabel"][disabled] {
        display: none !important;
      }
    </style>
    """,
    unsafe_allow_html=True
)

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

    with st.form("login_form"):
        name = st.text_input("Name")
        password = st.text_input("Password", type="password")

        submitted_login = st.form_submit_button("Login")
        submitted_signup = st.form_submit_button("Sign Up")
    
    if submitted_login:
        user_type = search_user(name, password)
        if user_type:
            # only ban free users by IP
            if user_type == 'F':
                lock_time = get_lockout(client_id)
                if lock_time > time.time():
                    remaining = lock_time - time.time()
                    st.error(f"You have been timed out for {remaining:.0f}s")
                    st.stop()

            # at this point, login OK
            st.session_state['name']     = name
            st.session_state['auth_stat'] = True
            st.session_state['type']     = user_type
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
            if get_lockout(client_id) > time.time():
                st.error("You cannot create a new free account yet. Try again later.")
                st.stop()
            if add_user(name, 'F', password):
                st.success("Signup successful! Redirecting to login...")
                st.session_state['auth_stat'] = None
                set_page("login")
            else:
                st.error("Name already exists")
        else:
            st.error("Please fill in all fields")

    if submitted_login:
        st.session_state['auth_stat'] = None
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
        cur.execute("SELECT client_id, timestamp FROM upgrade")
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
                        cur.execute("DELETE FROM upgrade WHERE client_id = ?", (name,))
                        con.commit()
                        st.rerun()
                    if st.button("❌ Decline", key=f"decline_{name}"):
                        cur.execute("DELETE FROM upgrade WHERE client_id = ?", (name,))
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
        history = get_submission(st.session_state['client_id'])
        
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
            show_paid_user_metrics(st.session_state['client_id'])
            token_input = st.number_input("Enter Tokens", min_value=1, step=1)
            
            if st.button("Add Tokens"):
                update_token(st.session_state['client_id'], token_input, 0)
                st.rerun()
            
            if st.button("View Submission History"):
                set_page("history")
        
        elif st.session_state['type'] == 'F':
            lock_time = get_lockout(client_id)
            if lock_time and lock_time < time.time():
                remove_lockout(client_id)
            
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
            st.markdown("### 📤 Upload a `.txt` file")
            uploaded = st.file_uploader("Choose a text file", type=["txt"])
            if uploaded:
                st.session_state['uploaded_file'] = uploaded
                file_text = uploaded.read().decode("utf-8")
            elif st.session_state['uploaded_file'] is not None and uploaded is None:
                st.session_state['uploaded_file'] = None

            if st.session_state['uploaded_file'] is None:
                st.markdown("### 💻 Or input your text:")
                typed_input = st.text_area(label="Your text:", placeholder="Start typing here...", height=170)

            user_input = (typed_input or file_text).rstrip()

            word_count = len(user_input.split())
            if st.session_state['type'] == 'F' and word_count > 20:
                st.markdown(f"<span style='color:red;'>Word count: {word_count} (Limit: 20. Submitting will result in a 3 minute timeout.)</span>", unsafe_allow_html=True)
            elif st.session_state['type'] == 'P':
                available, _ = get_token(st.session_state['client_id'])
                if word_count > available:
                    st.markdown(f"<span style='color:red;'>Word count: {word_count} (Exceeds available tokens: {available}. Submitting will cut your tokens in half.)</span>", unsafe_allow_html=True)
                else:
                    st.write(f"Word count: {word_count}")
            else:
                st.write(f"Word count: {word_count}")

            # ─── Submit button ───
            if st.button("Submit"):
                if user_input.strip():
                    word_count = len(user_input.split())
                    instruction_like = (
                        re.search(
                            r"(correct grammar|output only|do not explain|return it unchanged|fix (spelling|punctuation))",
                            user_input.lower()
                        )
                        and word_count < 25
                    )
                    if instruction_like:
                        st.warning(
                            "⚠️ Your input looks like an instruction. "
                            "If you're trying to correct a real sentence, rephrase it."
                        )
                    else:
                        # Free user flow
                        if st.session_state['type'] == 'F':
                            if word_count > 20:
                                set_lockout(client_id, 180)
                                logout_user()
                            else:
                                st.session_state["user_input"] = user_input
                                correct_text(user_input)

                        # Paid user flow: defer to confirmation
                        elif st.session_state['type'] == 'P':
                            available, used = get_token(st.session_state['client_id'])
                            if available >= word_count:
                                # flag for confirmation on next rerun
                                st.session_state["pending_submit"] = True
                                st.session_state["pending_input"]  = user_input
                                st.session_state["pending_count"]  = word_count
                            else:
                                penalty = available // 2
                                update_token(
                                    st.session_state['client_id'],
                                    -penalty,
                                    penalty
                                )
                                new_available, _ = get_token(st.session_state['client_id'])
                                st.warning(
                                    f"⚠️ Not enough tokens. "
                                    f"Half your tokens were deducted. Remaining: {new_available}"
                                )
                                st.stop()
                else:
                    st.warning("Input can't be empty.")

            # ─── Confirmation UI for paid users ───
            if st.session_state.get("pending_submit"):
                tokens = st.session_state["pending_count"]
                st.warning(f"⚠️ {tokens} tokens will be deducted. Are you sure?")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Yes, submit", key="confirm_submit"):
                        # perform the correction
                        correct_text(st.session_state["pending_input"])
                        # clear the pending flags
                        for k in ("pending_submit", "pending_count"):
                            st.session_state.pop(k, None)
                        st.rerun()
                with col2:
                    if st.button("Cancel", key="cancel_submit"):
                        # abort
                        for k in ("pending_submit", "pending_input", "pending_count"):
                            st.session_state.pop(k, None)

            if st.session_state.get("downloaded_success"):
                st.success(st.session_state["downloaded_success"])
                del st.session_state["downloaded_success"]

            if st.session_state.get("rendered_html") and not st.session_state.get("can_download"):
                st.subheader("✅ Corrected Text")
                raw = st.session_state["rendered_html"]
                wrapped = wrap_scrollable(raw)
                edited  = html_viewer(html=wrapped, height=300)
                if edited is not None:
                    st.session_state["corrected_text"] = edited

            if st.session_state['type'] == 'P':
                if st.session_state.get("corrected_text") and not st.session_state.get("can_download"):

                    # 1) First click: mark that we’re “confirming purchase”
                    if not st.session_state.get("confirming_purchase"):
                        if st.button("🔒 Confirm Edits"):
                            st.session_state["confirming_purchase"] = True
                            st.rerun()
                        st.markdown(
                            "⚠️ Pressing this will lock further edits.",
                            unsafe_allow_html=True
                        )

                    # 2) Now show cost + Yes/No
                    else:
                        clean_text = html_to_clean_text(st.session_state["corrected_text"])

                        # cost it out in one line
                        tokens = count_price(st.session_state["pending_input"], clean_text)
                        st.warning(f"⚠️ This will cost you {tokens} tokens. Proceed?")

                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("✅ Yes", key="confirm_yes"):
                                update_token(
                                    st.session_state['client_id'],
                                    -tokens,  # subtract from available
                                    tokens    # add to used
                                )
                                st.session_state["can_download"]        = True
                                st.session_state["confirming_purchase"] = False
                                st.session_state["tokens"]              = tokens
                                st.rerun()
                        with c2:
                            if st.button("❌ No", key="confirm_no"):
                                st.session_state["confirming_purchase"] = False
                                st.info("Edit confirmation cancelled.")
                                st.rerun()

                if st.session_state.get("can_download"):
                    st.markdown("### 📄 Preview of Approved Edits")

                    clean_text = html_to_clean_text(st.session_state["corrected_text"])

                    st.text_area("", clean_text, height=200, disabled=True)
                    st.success(f"💰 Deducted {st.session_state["tokens"]} tokens for confirmed edits.")

                    if st.download_button(
                        label="📥 Download .txt File (5 Tokens)",
                        data=clean_text,
                        file_name="corrected_text.txt",
                        mime="text/plain",
                    ):
                        available, _ = get_token(st.session_state['client_id'])
                        if available >= 5:
                            update_token(st.session_state['client_id'], -5, 5)
                            st.session_state["downloaded_success"] = f"File downloaded. 5 tokens deducted. Remaining: {available - 5}"
                            st.session_state["can_download"] = False
                            st.session_state["rendered_html"] = None
                            st.session_state["corrected_text"] = None
                            st.rerun()
                        else:
                            st.error("Not enough tokens to download the file.")

            render_blacklist_form()

        if st.button("Logout"):
            logout_user()