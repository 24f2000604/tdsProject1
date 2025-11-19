import requests
import json
import os
import time
import base64
import io
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv

# --- New Imports for Local Scraping & PDF ---
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from markdownify import markdownify as md
    import pypdf  # NEW: For handling PDFs locally
except ImportError:
    print("⚠️  Missing libraries.")
    print("Run: pip install selenium webdriver-manager markdownify pypdf")
    exit(1)

# --- Configuration ---
load_dotenv()

# Use Native OpenAI Key 
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_SK_KEY_HERE")

# Routing Configuration
AIPIPE_BASE_URL = "https://aipipe.org/openai/v1"
DIRECT_OPENAI_URL = "https://api.openai.com/v1"
MODEL_NAME = "gpt-4o" 

# --- GLOBAL CACHE ---
UPLOADED_FILES_CACHE = {}

# --- HELPER: User Credentials ---

def get_user_credentials() -> Tuple[str, str]:
    email = os.environ.get("USER_EMAIL", "default_email")
    secret = os.environ.get("USER_SECRET", "default_secret_code")
    return email, secret

# --- HELPER: Local Browser Logic ---

def get_page_source_local(url: str) -> str:
    """Uses Selenium to render the page (handling JavaScript) and returns HTML."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.get(url)
        time.sleep(3) 
        html_content = driver.page_source
        driver.quit()
        return html_content
    except Exception as e:
        print(f"  [Error] Local scraping failed: {e}")
        return requests.get(url).text

# --- HELPER: File Operations (DIRECT TO OPENAI) ---

def download_file_and_base64_encode(file_id: str) -> str:
    print(f"  [System] Downloading generated file: {file_id}...")
    download_url = f"{DIRECT_OPENAI_URL}/files/{file_id}/content"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "assistants=v2"
    }
    try:
        response = requests.get(download_url, headers=headers)
        response.raise_for_status()
        b64_data = base64.b64encode(response.content).decode('utf-8')
        return f"data:image/png;base64,{b64_data}"
    except Exception as e:
        print(f"  [Error] Failed to download file {file_id}: {e}")
        return None

# --- YOUR PROVIDED TOOLS (UPDATED) ---

def scrape_pdf(url: str) -> str:
    """Downloads a PDF and extracts its text content locally."""
    print(f"  [Tool] Extracting Text from PDF: {url}")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Use pypdf to read the binary content from memory
        with io.BytesIO(response.content) as open_pdf_file:
            reader = pypdf.PdfReader(open_pdf_file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
                
        print(f"  [Tool] PDF Extraction successful ({len(text)} chars).")
        return text[:20000] # Limit return size to avoid token overflow
        
    except Exception as e:
        return f"Error extracting PDF text: {str(e)}"

def download_and_process_file(url: str) -> str:
    """
    Downloads a file. 
    - If CSV/Text/JSON: Returns the raw content string (Direct Injection).
    - If Binary (PDF): Redirects to scrape_pdf.
    - Other Binaries (Img): Uploads to OpenAI.
    """
    
    if url.lower().endswith(".pdf"):
        return scrape_pdf(url)

    if url in UPLOADED_FILES_CACHE:
        cached_val = UPLOADED_FILES_CACHE[url]
        print(f"  [System] Using cached resource: {cached_val}")
        return cached_val

    print(f"  [Tool] Downloading external file: {url}")
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        
        content_type = r.headers.get('Content-Type', '').lower()
        url_lower = url.lower()
        
        is_text_data = (
            'text' in content_type or 
            'csv' in content_type or 
            'json' in content_type or
            url_lower.endswith('.csv') or
            url_lower.endswith('.json') or
            url_lower.endswith('.txt')
        )

        if is_text_data:
            print("  [Tool] Detected Text/CSV. Returning raw data directly to Agent.")
            UPLOADED_FILES_CACHE[url] = "Data already downloaded." 
            return r.text
        
        # Binary Upload Fallback
        print("  [Tool] Detected Binary. Uploading to OpenAI storage...")
        filename = os.path.basename(url.split("?")[0]) or "downloaded_file.dat"
        with open(filename, 'wb') as f:
            f.write(r.content)

        upload_url = f"{DIRECT_OPENAI_URL}/files"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        
        with open(filename, 'rb') as f:
            files = {'file': (filename, f), 'purpose': (None, 'assistants')}
            response = requests.post(upload_url, headers=headers, files=files)
        
        response.raise_for_status()
        file_id = response.json()['id']
        
        UPLOADED_FILES_CACHE[url] = f"File ID: {file_id}"
        os.remove(filename)
        print(f"  [Tool] File ready. ID: {file_id}")
        return f"File uploaded successfully. ID: {file_id}. Use this ID with Code Interpreter tools."
        
    except Exception as e:
        return f"Error processing file: {str(e)}"

def transcribe_audio_file(url: str) -> str:
    print(f"  [Tool] Transcribing Audio: {url}")
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        
        filename = "temp_audio_clip.mp3"
        if url.endswith(".opus"): filename = "temp_audio_clip.ogg"

        with open(filename, 'wb') as f:
            f.write(r.content)
            
        transcribe_url = f"{DIRECT_OPENAI_URL}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        
        with open(filename, "rb") as f:
            mime = "audio/ogg" if filename.endswith(".ogg") else "audio/mpeg"
            files = {
                "file": (filename, f, mime),
                "model": (None, "whisper-1")
            }
            response = requests.post(transcribe_url, headers=headers, files=files)
            
        if response.status_code != 200:
            return f"Error transcribing: {response.text}"
            
        transcript_text = response.json().get("text", "")
        print(f"  [Tool] Transcription result: '{transcript_text[:50]}...'")
        if os.path.exists(filename): os.remove(filename)
        return transcript_text
    except Exception as e:
        return f"Error during transcription: {str(e)}"

def get_latest_file_id_from_thread(thread_id: str) -> str:
    try:
        url = f"{AIPIPE_BASE_URL}/threads/{thread_id}/messages"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "assistants=v2"
        }
        response = requests.get(url, headers=headers)
        messages = response.json()
        for msg in messages.get('data', []):
            if msg['role'] == 'assistant':
                for content in msg['content']:
                    if content['type'] == 'image_file':
                        return content['image_file']['file_id']
        return None
    except Exception:
        return None

def scrape_md(url):
    print(f"  [Tool] Scraping (Markdown + Local JS): {url}")
    html_content = get_page_source_local(url)
    return md(html_content)

def scrape_html(url):
    print(f"  [Tool] Scraping (HTML + Local JS): {url}")
    return get_page_source_local(url)

def post_json(url, data):
    print(f"  [Tool] POST Request: {url},data:{data}")
    headers = { 'Content-Type': 'application/json' }
    r = requests.post(url, json=data, headers=headers)
    print(f"  [Tool] Response: {r.status_code} - {r.text[:200]}")
    return r.json()

def get_json(url):
    print(f"  [Tool] GET Request: {url}")
    headers = { 'Content-Type': 'application/json' }
    r = requests.get(url, headers=headers)
    return r.json()

def make_openai_request(endpoint: str, method: str = "GET", data: Dict[str, Any] = None) -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "assistants=v2"
    }
    url = f"{AIPIPE_BASE_URL}/{endpoint}"
    if method == "POST" and data is None: data = {}
    
    try:
        if method == "POST": response = requests.post(url, headers=headers, json=data)
        else: response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"\n❌ HTTP Error {e.response.status_code} for {url}")
        print(f"Response Body: {e.response.text}")
        raise e

# --- ASSISTANT CREATION ---

def create_assistant():
    print("Creating/Updating Assistant...")
    payload = {
        "name": "Full-Stack Data Agent",
        "instructions": (
            "You are an autonomous, full-stack data agent. You operate in a strict pipeline to solve data quizzes. USE THE CODE INTERPRITER TOOL FOR DATA ANYLISYS\n\n"
            "### 1. SOURCING & DISCOVERY (PRIORITY):\n"
            "   - **Scrape Page**: Use `web_scraper` to read text/HTML. prefer html and check using scraping tools whether the page contains a file as it is more cost effective\n"
            "   - **Check for Audio**: If page has mp3/wav/opus, call `audio_transcriber`.\n"
            "   - **CSV/JSON**: Use `web_downloader` to get raw text content directly.\n"
            "   - **PDF**: Use `pdf_scraper` to extract text content directly. DO NOT download PDFs as files.\n"
            "   - **CRITICAL**: Always prefer extracting text (CSV/PDF) directly into the chat context over file uploads.\n\n"
            "### 2. PROCESSING (Code Interpreter):\n"
            "   - **Combine Info**: Use info from audio/text/PDF to filter the CSV data.\n"
            "   - Analyze data using Pandas/SciPy.\n"
            "   - Generate charts using Matplotlib if requested.\n\n"
            "### 3. SUBMISSION:\n"
            "   - Use `api_request` with method='POST'.\n"
            "   - If chart needed, set value to '__LATEST_FILE__'."
        ),
        "model": MODEL_NAME,
        "tools": [
            {"type": "code_interpreter"},
            {
                "type": "function",
                "function": {
                    "name": "web_scraper",
                    "description": "Scrapes a website page text. Handles JavaScript. Returns HTML/Markdown.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}, "format": {"type": "string", "enum": ["html", "markdown"]}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_downloader",
                    "description": "Downloads a file. If CSV/JSON, returns raw text content. If Binary, uploads to OpenAI.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "pdf_scraper",
                    "description": "Downloads a PDF and extracts the text content directly. Use this for all PDF links.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "audio_transcriber",
                    "description": "Downloads an audio file and returns the transcribed text.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "api_request",
                    "description": "Makes a standard HTTP request (GET/POST).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "method": {"type": "string", "enum": ["GET", "POST"]},
                            "data_json": {"type": "string"}
                        },
                        "required": ["url", "method"]
                    }
                }
            }
        ]
    }
    return make_openai_request("assistants", method="POST", data=payload)

# --- EXECUTION LOGIC ---

def process_run_loop(thread_id, run_id):
    print(f"Polling Run ID: {run_id}")
    while True:
        time.sleep(2)
        run = make_openai_request(f"threads/{thread_id}/runs/{run_id}", method="GET")
        status = run['status']
        print(f"Status: {status}...", end='\r')

        if status == "completed":
            print("\nRun Completed!")
            return run

        elif status == "requires_action":
            print("\n🤖 Agent requires external tool execution...")
            tool_outputs = []
            required_actions = run['required_action']['submit_tool_outputs']['tool_calls']
            
            for tool_call in required_actions:
                func_name = tool_call['function']['name']
                args = json.loads(tool_call['function']['arguments'])
                call_id = tool_call['id']
                result = "Error"

                try:
                    if func_name == "web_scraper":
                        fmt = args.get('format', 'html')
                        result = scrape_html(args['url']) if fmt == 'html' else scrape_md(args['url'])

                    elif func_name == "web_downloader":
                        result = download_and_process_file(args['url'])
                    
                    elif func_name == "pdf_scraper":
                        result = scrape_pdf(args['url'])

                    elif func_name == "audio_transcriber":
                        result = transcribe_audio_file(args['url'])

                    elif func_name == "api_request":
                        if args['method'] == "GET":
                            result = json.dumps(get_json(args['url']))
                        else:
                            data_payload = json.loads(args.get('data_json', '{}'))
                            for key, value in data_payload.items():
                                if value == "__LATEST_FILE__":
                                    print("  [System] Injecting chart...")
                                    file_id = get_latest_file_id_from_thread(thread_id)
                                    if file_id: data_payload[key] = download_file_and_base64_encode(file_id)
                            result = json.dumps(post_json(args['url'], data_payload))
                except Exception as e:
                    result = f"Error: {str(e)}"
                    print(f"  [Error] Tool Execution Failed: {e}")

                tool_outputs.append({"tool_call_id": call_id, "output": str(result)})
            
            make_openai_request(
                f"threads/{thread_id}/runs/{run_id}/submit_tool_outputs",
                method="POST",
                data={"tool_outputs": tool_outputs}
            )
            
        elif status in ["failed", "cancelled", "expired"]:
            print(f"\nRun Failed: {run.get('last_error')}")
            break
    return run

# --- MAIN FLOW ---

def solve_quiz_question(question_prompt):
    try:
        assistant = create_assistant()
        assistant_id = assistant['id']
        print("Creating Run...")
        
        run_payload = {
            "assistant_id": assistant_id,
            "thread": {"messages": [{"role": "user", "content": question_prompt}]},
            "model": MODEL_NAME
        }
        run = make_openai_request("threads/runs", method="POST", data=run_payload)
        final_run = process_run_loop(run['thread_id'], run['id'])

        if final_run and final_run['status'] == 'completed':
            messages = make_openai_request(f"threads/{run['thread_id']}/messages", method="GET")
            if messages.get('data'):
                print("\n--- Final AI Message ---")
                latest_msg = messages['data'][0]
                for content_part in latest_msg['content']:
                    if content_part['type'] == 'text':
                        print(content_part['text']['value'])
                    elif content_part['type'] == 'image_file':
                        print(f"[Image File Generated: {content_part['image_file']['file_id']}]")

    except Exception as e:
        print(f"\n[Fatal Error] {e}")

if __name__ == "__main__":
    if "YOUR_OPENAI_SK_KEY_HERE" in OPENAI_API_KEY:
        print("⚠️  Please set OPENAI_API_KEY in your .env file.")

    email, secret = get_user_credentials()
    
    prompt = (
        f"solve https://tds-llm-analysis.s-anand.net/demo, "
        f"When posting the JSON, include 'student_email': '{email}' and 'secret_code': '{secret}' in the payload."
        f"keep checking any urls provided until you get the final answer. a succesful response might cointain urls with additional problems"
    )



    solve_quiz_question(prompt)