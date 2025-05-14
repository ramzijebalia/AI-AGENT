import os
import json
from typing import TypedDict, Annotated, Union, List
from dotenv import load_dotenv
from langchain.agents import AgentExecutor, Tool, create_react_agent
from langchain.tools import tool
from langchain_core.callbacks import BaseCallbackHandler
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import BaseMessage
from langchain_core.agents import AgentFinish, AgentAction
from langgraph.graph import Graph, END
from langgraph.prebuilt import ToolNode
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from email.mime.text import MIMEText
import base64
import requests
from bs4 import BeautifulSoup
import operator
from pydantic import BaseModel, EmailStr
from typing import Optional

# Load environment variables
load_dotenv()

# Initialize Gemini LLM 
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-preview-04-17",
    google_api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0.3
)

# Define Agent State
class AgentState(TypedDict):
    input: str
    chat_history: List[BaseMessage]
    agent_outcome: Union[AgentAction, AgentFinish, None]
    intermediate_steps: Annotated[List[tuple[AgentAction, str]], operator.add]

# Gmail API Setup
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.send']

def authenticate_gmail():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

# Tool Definitions with MCP
@tool
def search_emails(query: str, max_results: int = 5) -> str:
    """Search emails in Gmail inbox using Gmail search syntax"""
    try:
        creds = authenticate_gmail()
        service = build('gmail', 'v1', credentials=creds)
        
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results
        ).execute()
        
        messages = []
        for msg in results.get('messages', []):
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata'
            ).execute()
            
            headers = {h['name']: h['value'] for h in msg_data['payload']['headers']}
            messages.append({
                'From': headers.get('From'),
                'Subject': headers.get('Subject'),
                'Date': headers.get('Date'),
                'Snippet': msg_data.get('snippet', '')[:100] + '...'
            })
        
        return json.dumps(messages, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

class EmailInput(BaseModel):
    to: str
    subject: str
    body: str

@tool
def send_email(input_str: str) -> str:
    """Send an email through Gmail.
    
    Args:
        input_str: A string containing email details in the format:
                  to="email@example.com", subject="Subject", body="Message content"
    
    Returns:
        str: Success or error message
    """
    try:
        # Get user name from environment variables
        user_name = os.getenv("USER_NAME", "[Your Name]")  # Default fallback

        # Improved parsing that handles multi-line bodies
        params = {}
        current_key = None
        current_value = []
        
        # Split by commas not inside quotes
        parts = []
        in_quotes = False
        part_start = 0
        
        for i, char in enumerate(input_str):
            if char == '"':
                in_quotes = not in_quotes
            elif char == ',' and not in_quotes:
                parts.append(input_str[part_start:i].strip())
                part_start = i + 1
        parts.append(input_str[part_start:].strip())
        
        # Parse each part
        for part in parts:
            if '=' not in part:
                if current_key is not None:
                    current_value.append(part)
                continue
                
            # If we have a current key, save its value first
            if current_key is not None:
                params[current_key] = ' '.join(current_value).strip('"')
                current_value = []
                
            key, value = part.split('=', 1)
            current_key = key.strip()
            current_value.append(value.strip())
        
        # Add the last parameter
        if current_key is not None:
            params[current_key] = ' '.join(current_value).strip('"')
        
        # Validate required fields
        required_fields = ['to', 'subject', 'body']
        missing_fields = [field for field in required_fields if field not in params]
        if missing_fields:
            return f"Error: Missing required fields: {', '.join(missing_fields)}"
            
        # Clean up inputs
        to = params['to'].strip()
        subject = params['subject'].strip()
        body = params['body'].strip()
        # Replace [Your Name] with actual user name
        body = body.replace("[Your Name]", user_name)
        
        # Convert literal \n to actual newlines
        body = body.replace('\\n', '\n')
        
        # Validate email format
        if '@' not in to or '.' not in to:
            return "Error: Invalid email address format"
            
        creds = authenticate_gmail()
        service = build('gmail', 'v1', credentials=creds)
        
        # Create message with proper formatting
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        
        # Encode and send
        raw = base64.urlsafe_b64encode(message.as_bytes())
        raw = raw.decode()
        
        service.users().messages().send(
            userId='me',
            body={'raw': raw}
        ).execute()
        
        return f"Email successfully sent to {to}"
    except Exception as e:
        return f"Error sending email: {str(e)}"

@tool
def google_search(query: str, num_results: int = 3) -> str:
    """Perform a Google search using Custom Search JSON API"""
    try:
        api_key = os.getenv("GOOGLE_CSE_API_KEY")
        cx = os.getenv("GOOGLE_CSE_CX")
        
        if not api_key or not cx:
            return "Error: Missing Google CSE API key or CX"
        
        url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={api_key}&cx={cx}&num={num_results}"
        response = requests.get(url)
        results = response.json()
        
        if "items" not in results:
            return "No results found"
            
        output = []
        for item in results["items"]:
            output.append(f"Title: {item.get('title', 'N/A')}\n"
                         f"Link: {item.get('link', 'N/A')}\n"
                         f"Snippet: {item.get('snippet', 'N/A')}\n")
            
        return "\n".join(output)
    except Exception as e:
        return f"Search error: {str(e)}"

@tool
def web_scraping(url: str) -> str:
    """Scrape and analyze webpage content.
    
    Args:
        url: The URL to scrape and analyze
    
    Returns:
        str: Analysis of the webpage content
    """
    try:
        # Add headers to mimic a browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Raise an exception for bad status codes
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()
            
        # Extract title
        title = soup.title.string if soup.title else "No title found"
        
        # Extract main content
        main_content = []
        
        # Try to find the main content area
        main_tags = soup.find_all(['article', 'main', 'div'], class_=['content', 'main', 'article'])
        if main_tags:
            content = main_tags[0]
        else:
            content = soup.body if soup.body else soup
            
        # Extract text from paragraphs and headings
        for tag in content.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            text = tag.get_text().strip()
            if text:
                main_content.append(text)
        
        # Clean and format the content
        content_text = '\n'.join(main_content)
        
        # Create a summary
        summary = f"""Webpage Analysis:
Title: {title}

Main Content Summary:
{content_text[:1000]}...

Key Points:
1. The page appears to be about: {content_text[:200]}...
2. Main topics discussed: {', '.join([line[:50] for line in main_content[:3]])}
3. Content length: {len(content_text)} characters

Note: This is a summary of the publicly accessible content. Some content may be restricted or require authentication."""
        
        return summary
        
    except requests.exceptions.RequestException as e:
        return f"Error accessing the URL: {str(e)}"
    except Exception as e:
        return f"Error analyzing the webpage: {str(e)}"

# Tool Setup with MCP
tools = [search_emails, send_email, google_search, web_scraping]
tool_names = [t.name for t in tools]

# Callback Handler
class ActionLogger(BaseCallbackHandler):
    def on_tool_start(self, serialized, input_str, **kwargs):
        print(f"\n🔧 Action: {serialized.get('name', 'unknown')}")
        print(f"   Input: {input_str}")
    def on_tool_end(self, output, **kwargs):
        print(f"   Result: {output[:200]}...")

# Enhanced Prompt Template with MCP
PROMPT_TEMPLATE = """You are an AI assistant with access to various tools. Follow these rules:

FOR EMAIL COMPOSITION:
- When asked to write/send an email, carefully extract:
  1. Recipient email address (must be valid email format)
  2. Clear subject line summarizing the purpose
  3. Detailed body content that includes:
     - Professional greeting (use recipient's name if known)
     - Clear explanation of the situation
     - Any necessary details or context
     - Professional closing with your name
- Always maintain professional tone
- If reason isn't specified, ask for clarification

AVAILABLE TOOLS:
{tools}

TOOL NAMES:
{tool_names}

RESPONSE FORMAT:
For tool use:
Thought: Do I need a tool? Yes
Action: tool_name (must be one of {tool_names})
Action Input: properly_formatted_input
Observation: tool_result

For final answer:
Thought: Do I need a tool? No
Final Answer: your_response

EMAIL FORMAT EXAMPLE:
Action: send_email
Action Input: to="manager@company.com", subject="Unable to attend team meeting", body="Dear [Name],\n\nI regret to inform you that I won't be able to attend tomorrow's team meeting due to [reason].\n\nI've prepared my updates and shared them with [colleague] who can present them on my behalf.\n\nPlease let me know if you need anything else from me.\n\nBest regards,\n[Your Name]"

CURRENT TASK: {input}
CHAT HISTORY: {chat_history}
PAST ACTIONS: {agent_scratchpad}"""

prompt = PromptTemplate(
    template=PROMPT_TEMPLATE,
    input_variables=["input", "tools", "tool_names", "chat_history", "agent_scratchpad"]
)

# Agent Setup with LangGraph
def create_agent():
    agent = create_react_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        callbacks=[ActionLogger()],
        verbose=True,
        handle_parsing_errors=True
    )
    return agent_executor

# LangGraph Workflow
def create_workflow():
    workflow = Graph()
    
    # Agent Node
    def run_agent(state: AgentState):
        agent_executor = create_agent()
        result = agent_executor.invoke({
            "input": state["input"],
            "chat_history": state["chat_history"],
            "tools": "\n".join([f"{t.name}: {t.description}" for t in tools]),
            "tool_names": ", ".join(tool_names),
            "agent_scratchpad": ""
        })
        return {"agent_outcome": result}
    
    workflow.add_node("agent", run_agent)
    workflow.add_node("tools", ToolNode(tools))
    
    # Define transitions
    workflow.set_entry_point("agent")
    
    def should_continue(state: AgentState):
        if isinstance(state["agent_outcome"], AgentFinish):
            return "end"
        return "continue"
    
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "continue": "tools",
            "end": END
        }
    )
    
    workflow.add_edge("tools", "agent")
    
    return workflow.compile()

# Main execution
def run_agent(query: str, chat_history: List[BaseMessage] = None):
    if chat_history is None:
        chat_history = []
        
    print(f"\n🎯 Query: {query}")
    print("=" * 50)
    
    try:
        workflow = create_workflow()
        result = workflow.invoke({
            "input": query,
            "chat_history": chat_history,
            "agent_outcome": None,
            "intermediate_steps": []
        })
        
        print("\n✅ Result:")
        print(result["agent_outcome"]["output"])
        return result["agent_outcome"]["output"]
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return None
    finally:
        print("\n" + "=" * 50 + "\n")

if __name__ == "__main__":
    # First-run will open browser for OAuth authentication
    print("Gmail authentication will open in your browser...")
    
    # Initialize chat history
    chat_history = []
    
    print("\nAgent is ready! Type your query or 'exit' to quit.")
    print("=" * 50)
    
    while True:
        # Get user input
        user_input = input("\nYou: ")
        
        # Check for exit command
        if user_input.lower() in ['exit', 'quit']:
            print("Goodbye!")
            break
            
        # Run the agent with the user's query
        response = run_agent(user_input, chat_history)
        
        # Update chat history if we got a response
        if response:
            chat_history.append({"role": "user", "content": user_input})
            chat_history.append({"role": "assistant", "content": response})