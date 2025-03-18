import streamlit as st
import ollama
import difflib # Module to compare input with corrected text

st.set_page_config(page_title="Text Edit Name Placeholder")
st.title("📝 LLM-Based Text Editor")

# Creates the text box and Stores user input in the variable
user_input = st.text_area("Your text:", placeholder = "Start typing here...")
LLM_instruction = "You are a grammar correction AI. Fix errors grammar and spelling in the given text. You can allow informal words as long as they are spelled correctly. Do NOT provide ANY explanation. ONLY return corrected sentence."
 # Corrected words need CSS styling so they can be highlighted so a list is needed for that
printWords = []

if st.button("Submit") and user_input.strip():
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

    for status, oStart, oEnd, cStart, cEnd in diff.get_opcodes():
        if status == 'equal':
            printWords.extend(splitPut[cStart:cEnd])
        else:
            for x in range (cStart, cEnd):
                printWords.append(f'<span style="background-color: orangered; border-radius: 8px; padding: 0px 4px; display: inline-block;">{splitPut[x]}</span>')
    st.markdown(" ".join(printWords), unsafe_allow_html=True)
else: st.warning("Input can't be empty.")