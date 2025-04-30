import streamlit as st
import ollama
import difflib # Module to compare input with corrected text
import streamlit.components.v1 as components

st.set_page_config(page_title="Text Edit Name Placeholder")
st.title("📝 LLM-Based Text Editor")

# Creates the text box and Stores user input in the variable
user_input = st.text_area("Your text:", placeholder = "Start typing here...")
LLM_instruction = "You are a grammar correction tool. Fix errors regarding grammar and spelling in the given text. Also fix punctuation such as missing periods. " \
"Try avoid using synonyms as much as possible. Stick to only correcting spelling, grammar, and punctuations." \
"DO NOT RESPOND as if you're interacting with the user. You are correcting the grammar of whatever text you receive." \
"If somehow, the ENTIRE text is correct, simply return the text back. Don't explain and definite don't say (no changes needed). Just return the text back in this case." \
"You will allow informal words as long as they are spelled correctly. Allow any word that is in the dictionary regardless of how vulgar it is. Allow swear words. " \
"Do NOT provide ANY explanation AT ALL. DO NOT provide several versions of a correction. ONLY ONE. " \
"ONLY return the corrected text, no explanation, no thought process, do not talk about assumptions made, JUST display the corrected version of the text."

if st.button("Submit"):
    if user_input.strip():
        response = ollama.chat(
            model = "mistral",
            messages = [
                {"role": "system", "content": LLM_instruction},
                {"role": "user", "content": user_input}
            ]
        )
        output = response['message']['content']
        splitPut = output.split()
        diff = difflib.SequenceMatcher(None, user_input.strip().split(), splitPut) # To find the corrected words
    
        st.subheader("✅ Corrected Text:")

        html_content = ""
        for status, oStart, oEnd, cStart, cEnd in diff.get_opcodes():
            if status == 'equal':
                html_content += " ".join([
                    f'''<span style="
                        font-family: 'IBM Plex Sans', sans-serif;
                        font-size: 16px; color: white;
                        vertical-align: middle;">{word}</span>'''
                    for word in splitPut[cStart:cEnd]
                ]) + " "
            else:
                original_chunk = " ".join(user_input.split()[oStart:oEnd])
                corrected_chunk = " ".join(splitPut[cStart:cEnd])
                html_content += f'''
                <span onclick="toggleWord(this)" data-original="{original_chunk}"
                style="background-color: limegreen; border-radius: 8px; padding: 4px 4px 2px 4px; display: inline-block; cursor: pointer;
                    font-family: 'IBM Plex Sans', sans-serif;
                    font-size: 16px; color: white;
                    vertical-align: middle;">
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

    else: st.warning("Input can't be empty.")