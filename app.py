import streamlit as st
import re
from io import StringIO
from contextlib import redirect_stdout
from main1 import run_agent

# Set up the Streamlit app
st.set_page_config(page_title="AI Agent Chat", layout="centered")
st.title("💬 AI Assistant")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Function to clean console output
def clean_output(text):
    # Remove ANSI escape codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    cleaned = ansi_escape.sub('', text)
    
    # Remove specific unwanted patterns
    cleaned = cleaned.replace("> Finished chain.", "")
    cleaned = cleaned.replace("❌ Error: No message found in input", "")
    cleaned = cleaned.replace("==================================================", "")
    
    return cleaned.strip()

# Tool status messages mapping
TOOL_STATUS_MESSAGES = {
    "search_emails": "🔍 Searching your inbox...",
    "send_email": "📧 Preparing to send email...",
    "google_search": "🌐 Searching the web...",
    "web_scraping": "🕸️ Analyzing webpage content..."
}

def get_tool_status_message(tool_name):
    """Get the appropriate status message for the tool being used"""
    return TOOL_STATUS_MESSAGES.get(tool_name, "🤖 Processing your request...")

# Modified agent runner that captures tool usage
def run_agent_clean(query, chat_history):
    output_buffer = StringIO()
    with redirect_stdout(output_buffer):
        try:
            response = run_agent(query, chat_history)
            
            # Extract response from different possible formats
            if isinstance(response, dict) and 'output' in response:
                response = response['output']
            elif response is None:
                output_text = output_buffer.getvalue()
                if "Final Answer:" in output_text:
                    response = output_text.split("Final Answer:")[-1].split("> Finished chain.")[0].strip()
            
            # Clean the response if we got one
            if response:
                return clean_output(response)
                
        except Exception as e:
            return f"Error: {str(e)}"
    
    return None

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User input handling
if prompt := st.chat_input("How can I help you today?"):
    # Add user message
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Get and display agent response
    with st.chat_message("assistant"):
        # First show a generic thinking message
        with st.spinner("🤖 Analyzing your request..."):
            # Get the raw output to detect tool usage
            output_buffer = StringIO()
            with redirect_stdout(output_buffer):
                response = run_agent(prompt, st.session_state.messages)
                output_text = output_buffer.getvalue()
            
            # Check which tool is being used (if any)
            tool_used = None
            for tool_name in TOOL_STATUS_MESSAGES.keys():
                if f"Action: {tool_name}" in output_text:
                    tool_used = tool_name
                    break
            
            # Show appropriate status message
            if tool_used:
                with st.spinner(get_tool_status_message(tool_used)):
                    response = run_agent_clean(prompt, st.session_state.messages)
            else:
                response = run_agent_clean(prompt, st.session_state.messages)
            
            if response:
                st.markdown(response)
            else:
                st.error("Sorry, I couldn't generate a response.")
    
    # Add response to history if successful
    if response:
        st.session_state.messages.append({"role": "assistant", "content": response})

# Simple sidebar
with st.sidebar:
    st.header("Controls")
    if st.button("Clear Conversation", type="primary"):
        st.session_state.messages = []
        st.rerun()
    
    st.divider()
    st.markdown("### Capabilities")
    st.markdown("""
    - Email management
    - Web search
    - Web analysis
    - Multi-tool integration
    """)