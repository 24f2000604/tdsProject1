import requests
import json
import os
import time
import base64
import io
import zipfile  # Lightweight, built-in
from typing import Dict, Any, List, Tuple, Optional
from dotenv import load_dotenv

# --- Lightweight Imports for Scraping & PDF ---
# NOTE: Heavy processing (pandas, matplotlib, PIL) is offloaded to LLM Code Interpreter
# to minimize RAM usage on resource-constrained VMs (1GB RAM)
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from markdownify import markdownify as md
    import pypdf  # Lightweight PDF text extraction
except ImportError as e:
    print(f"⚠️  Missing libraries: {e}")
    print("Run: pip install selenium webdriver-manager markdownify pypdf")
    exit(1)

# Optional: JSONPath (lightweight)
try:
    from jsonpath_ng import parse as jsonpath_parse
    HAS_JSONPATH = True
except ImportError:
    HAS_JSONPATH = False
    print("⚠️  jsonpath-ng not installed. json_query tool will be limited.")

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
    """Uses Selenium with Chrome/ChromeDriver to render the page (handling JavaScript) and returns HTML."""
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
    - If PDF: Redirects to scrape_pdf.
    - If Excel (.xlsx/.xls): Redirects to parse_excel.
    - If ZIP: Redirects to extract_zip.
    - Other Binaries (Img): Uploads to OpenAI.
    """
    url_lower = url.lower()
    
    # Handle specific file types directly
    if url_lower.endswith(".pdf"):
        return scrape_pdf(url)
    
    if url_lower.endswith((".xlsx", ".xls")):
        return parse_excel(url)
    
    if url_lower.endswith(".zip"):
        return extract_zip(url)

    if url in UPLOADED_FILES_CACHE:
        cached_val = UPLOADED_FILES_CACHE[url]
        print(f"  [System] Using cached resource: {cached_val}")
        return cached_val

    print(f"  [Tool] Downloading external file: {url}")
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        
        content_type = r.headers.get('Content-Type', '').lower()
        
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

# --- LIGHTWEIGHT DATA TOOLS (Heavy processing offloaded to Code Interpreter) ---
# NOTE: These tools focus on DOWNLOADING data and passing it to the LLM sandbox
# to minimize RAM usage on the VM. Code Interpreter handles pandas/matplotlib/etc.

def download_excel_raw(url: str) -> str:
    """Downloads Excel file and uploads to OpenAI for Code Interpreter processing.
    
    Returns file ID for use with Code Interpreter (heavy processing done in sandbox).
    """
    print(f"  [Tool] Downloading Excel for Code Interpreter: {url}")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        # Save temporarily and upload to OpenAI
        filename = os.path.basename(url.split("?")[0]) or "data.xlsx"
        if not filename.endswith(('.xlsx', '.xls')):
            filename = "data.xlsx"
            
        with open(filename, 'wb') as f:
            f.write(response.content)
        
        # Upload to OpenAI for Code Interpreter
        upload_url = f"{DIRECT_OPENAI_URL}/files"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        
        with open(filename, 'rb') as f:
            files = {'file': (filename, f), 'purpose': (None, 'assistants')}
            api_response = requests.post(upload_url, headers=headers, files=files)
        
        api_response.raise_for_status()
        file_id = api_response.json()['id']
        os.remove(filename)
        
        print(f"  [Tool] Excel uploaded. File ID: {file_id}")
        return f"Excel file uploaded. File ID: {file_id}. Use Code Interpreter with pandas to read and process this file: pd.read_excel(file_path)"
        
    except Exception as e:
        return f"Error downloading Excel: {str(e)}"


def extract_tables_from_html(url: str) -> str:
    """Scrapes HTML and returns raw HTML for Code Interpreter to parse tables.
    
    Returns HTML content - use Code Interpreter with pd.read_html() for table extraction.
    """
    print(f"  [Tool] Extracting HTML for table parsing: {url}")
    try:
        html_content = get_page_source_local(url)
        
        # Return raw HTML - let Code Interpreter use pd.read_html()
        # This avoids loading pandas locally
        print(f"  [Tool] HTML fetched ({len(html_content)} chars). Use pd.read_html() in Code Interpreter.")
        return f"HTML content fetched. Use Code Interpreter with: `import pandas as pd; tables = pd.read_html('''...html content...''')` to extract tables.\n\nHTML Content:\n{html_content[:30000]}"
        
    except Exception as e:
        return f"Error fetching HTML: {str(e)}"


def extract_zip(url: str) -> str:
    """Downloads a ZIP file and lists/extracts text files inside (lightweight, built-in zipfile)."""
    print(f"  [Tool] Extracting ZIP: {url}")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            file_list = z.namelist()
            contents = []
            
            # Extract content from text-based files only
            text_extensions = ('.txt', '.csv', '.json', '.xml', '.html', '.md', '.py', '.js')
            for name in file_list:
                if name.lower().endswith(text_extensions) and not name.startswith('__'):
                    try:
                        content = z.read(name).decode('utf-8', errors='ignore')
                        contents.append(f"--- {name} ---\n{content[:8000]}")
                    except Exception:
                        contents.append(f"--- {name} --- (binary or unreadable)")
                        
            output = f"Files in archive: {file_list}\n\n" + "\n\n".join(contents)
            print(f"  [Tool] ZIP extraction successful ({len(file_list)} files).")
            return output[:25000]
        
    except Exception as e:
        return f"Error extracting ZIP: {str(e)}"


def query_json_path(url: str, jsonpath: str) -> str:
    """Downloads JSON and extracts data using JSONPath expression."""
    print(f"  [Tool] JSONPath Query: {url} -> {jsonpath}")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if HAS_JSONPATH:
            expr = jsonpath_parse(jsonpath)
            matches = [match.value for match in expr.find(data)]
            result = json.dumps(matches, indent=2, default=str)
            print(f"  [Tool] JSONPath found {len(matches)} match(es).")
        else:
            # Fallback: return full JSON for Code Interpreter to process
            result = f"JSONPath not available locally. Full JSON data:\n{json.dumps(data, indent=2, default=str)}"
            print(f"  [Tool] Returning full JSON for Code Interpreter processing.")
        
        return result[:20000]
        
    except Exception as e:
        return f"Error in JSONPath query: {str(e)}"


# --- Function Aliases (for backward compatibility) ---
def parse_excel(url: str) -> str:
    """Alias for download_excel_raw - for backward compatibility."""
    return download_excel_raw(url)


def extract_text_from_image(url: str, question: str = None) -> str:
    """Uses Vision API for image text extraction (no local OCR to save RAM)."""
    if question is None:
        question = "Extract ALL text visible in this image. Maintain formatting where possible."
    return analyze_image_with_vision(url, question)


def analyze_image_with_vision(url: str, question: str = "Describe this image in detail. If it contains text, extract all text. If it's a chart/graph, describe the data.") -> str:
    """Analyzes an image using OpenAI's vision capability (no local processing)."""
    print(f"  [Tool] Vision Analysis: {url}")
    try:
        # Download and encode image
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        b64_image = base64.b64encode(response.content).decode('utf-8')
        
        # Determine mime type from headers or URL
        content_type = response.headers.get('Content-Type', '').lower()
        url_lower = url.lower()
        
        if 'jpeg' in content_type or 'jpg' in content_type or url_lower.endswith(('.jpg', '.jpeg')):
            mime = 'image/jpeg'
        elif 'png' in content_type or url_lower.endswith('.png'):
            mime = 'image/png'
        elif 'gif' in content_type or url_lower.endswith('.gif'):
            mime = 'image/gif'
        elif 'webp' in content_type or url_lower.endswith('.webp'):
            mime = 'image/webp'
        else:
            mime = 'image/png'
        
        # Call OpenAI Vision API (processing happens on OpenAI's servers, not locally)
        vision_url = f"{DIRECT_OPENAI_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64_image}"}}
                    ]
                }
            ],
            "max_tokens": 2000
        }
        
        api_response = requests.post(vision_url, headers=headers, json=payload)
        api_response.raise_for_status()
        
        result = api_response.json()['choices'][0]['message']['content']
        print(f"  [Tool] Vision analysis complete ({len(result)} chars).")
        return result
        
    except Exception as e:
        return f"Error in vision analysis: {str(e)}"


def generate_chart_base64(data_csv: str, chart_type: str = "bar", x_col: str = None, y_col: str = None, title: str = "Chart") -> str:
    """
    LIGHTWEIGHT: Returns the CSV data with instructions to use Code Interpreter for chart generation.
    This avoids loading matplotlib locally on RAM-constrained VMs.
    """
    print(f"  [Tool] Chart request: {chart_type} - '{title}' (delegating to Code Interpreter)")
    
    # Return the data with instructions - Code Interpreter will generate the actual chart
    return (
        f"CHART_REQUEST: Please use Code Interpreter to generate a {chart_type} chart.\n"
        f"Title: {title}\n"
        f"X Column: {x_col or 'auto-detect first column'}\n"
        f"Y Column: {y_col or 'auto-detect first numeric column'}\n"
        f"DATA (CSV format):\n{data_csv}\n\n"
        f"Generate the chart using matplotlib in Code Interpreter and return the base64 PNG."
    )

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
            "You are an autonomous, full-stack data agent. You operate in a strict pipeline to solve data quizzes. USE THE CODE INTERPRETER TOOL FOR DATA ANALYSIS.\n\n"
            "### CRITICAL RULES:\n"
            "   - After submitting an answer, if the response contains a new `url` field, IMMEDIATELY visit and solve that URL too.\n"
            "   - Continue solving URLs until you receive a response with NO new url or `correct: true` with no url.\n"
            "   - Do NOT hardcode any URLs. Always extract submission URLs from the quiz page.\n\n"
            "### 1. SOURCING & DISCOVERY (PRIORITY):\n"
            "   - **Scrape Page**: Use `web_scraper` to read text/HTML. Prefer HTML format first.\n"
            "   - **Check for Audio**: If page has mp3/wav/opus, call `audio_transcriber`.\n"
            "   - **CSV/JSON/Text**: Use `web_downloader` to get raw text content directly.\n"
            "   - **PDF**: Use `pdf_scraper` to extract text content directly.\n"
            "   - **Excel (.xlsx/.xls)**: Use `excel_parser` to extract all sheets as CSV.\n"
            "   - **ZIP Archives**: Use `zip_extractor` to list and extract text files.\n"
            "   - **Images with Text**: Use `image_ocr` for text extraction, or `image_analyzer` for visual analysis.\n"
            "   - **HTML Tables**: Use `table_extractor` to extract tables from web pages.\n"
            "   - **JSON with complex structure**: Use `json_query` with JSONPath to extract specific data.\n"
            "   - **CRITICAL**: Always prefer extracting text directly into the chat context over file uploads.\n\n"
            "### 2. PROCESSING (Code Interpreter):\n"
            "   - Analyze data using Pandas/NumPy/SciPy.\n"
            "   - Perform statistical analysis, filtering, aggregation.\n"
            "   - Generate charts using Matplotlib if requested (or use `chart_generator` tool).\n"
            "   - Handle geo-spatial or network analysis as needed.\n\n"
            "### 3. SUBMISSION:\n"
            "   - Use `api_request` with method='POST' to the URL specified in the quiz.\n"
            "   - Include: email, secret, url (original quiz URL), and answer.\n"
            "   - Answer types: boolean, number, string, base64 URI, or JSON object.\n"
            "   - If chart/image needed, generate it in Code Interpreter and include as base64 data URI.\n"
            "   - After submission, CHECK THE RESPONSE for a new `url` field and continue if present.\n"
            "   - Follow the exact JSON format specified in the quiz instructions."
        ),
        "model": MODEL_NAME,
        "tools": [
            {"type": "code_interpreter"},
            {
                "type": "function",
                "function": {
                    "name": "web_scraper",
                    "description": "Scrapes a website page text. Handles JavaScript-rendered pages. Returns HTML or Markdown.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The URL to scrape"},
                            "format": {"type": "string", "enum": ["html", "markdown"], "description": "Output format (default: html)"}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_downloader",
                    "description": "Downloads a file from URL. Returns raw text for CSV/JSON/TXT files. For PDFs, extracts text. For binary files, uploads to storage.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string", "description": "The file URL to download"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "pdf_scraper",
                    "description": "Downloads a PDF and extracts all text content directly. Use for any PDF file links.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string", "description": "The PDF URL"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "audio_transcriber",
                    "description": "Downloads an audio file (mp3/wav/opus/ogg) and returns transcribed text using Whisper.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string", "description": "The audio file URL"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "api_request",
                    "description": "Makes HTTP GET or POST requests. For POST, provide JSON data as a string.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The API endpoint URL"},
                            "method": {"type": "string", "enum": ["GET", "POST"], "description": "HTTP method"},
                            "data_json": {"type": "string", "description": "JSON payload as string (for POST requests)"}
                        },
                        "required": ["url", "method"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "excel_parser",
                    "description": "Downloads an Excel file (.xlsx/.xls) and extracts all sheets as CSV text.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string", "description": "The Excel file URL"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "image_ocr",
                    "description": "Downloads an image and extracts text using OCR (Tesseract). Use for images containing text.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string", "description": "The image URL"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "table_extractor",
                    "description": "Scrapes all HTML tables from a web page and returns them as CSV text. Handles JavaScript-rendered pages.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string", "description": "The web page URL containing tables"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "zip_extractor",
                    "description": "Downloads a ZIP archive and extracts/lists text-based files inside (txt, csv, json, xml, etc.).",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string", "description": "The ZIP file URL"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "json_query",
                    "description": "Downloads JSON from URL and extracts data using JSONPath expression (e.g., '$.data[*].value').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The JSON API/file URL"},
                            "jsonpath": {"type": "string", "description": "JSONPath expression to extract data"}
                        },
                        "required": ["url", "jsonpath"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "image_analyzer",
                    "description": "Analyzes an image using AI vision. Use for charts, diagrams, screenshots, or any visual content that needs interpretation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The image URL"},
                            "question": {"type": "string", "description": "What to analyze or extract from the image"}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "chart_generator",
                    "description": "Generates a chart from CSV data and returns as base64 PNG image.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "data_csv": {"type": "string", "description": "CSV data as string"},
                            "chart_type": {"type": "string", "enum": ["bar", "line", "scatter", "pie", "hist"], "description": "Type of chart"},
                            "x_col": {"type": "string", "description": "Column name for X axis"},
                            "y_col": {"type": "string", "description": "Column name for Y axis"},
                            "title": {"type": "string", "description": "Chart title"}
                        },
                        "required": ["data_csv"]
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
                    
                    # --- NEW TOOL HANDLERS ---
                    elif func_name == "excel_parser":
                        result = parse_excel(args['url'])
                    
                    elif func_name == "image_ocr":
                        result = extract_text_from_image(args['url'])
                    
                    elif func_name == "table_extractor":
                        result = extract_tables_from_html(args['url'])
                    
                    elif func_name == "zip_extractor":
                        result = extract_zip(args['url'])
                    
                    elif func_name == "json_query":
                        result = query_json_path(args['url'], args['jsonpath'])
                    
                    elif func_name == "image_analyzer":
                        question = args.get('question', 'Describe this image in detail.')
                        result = analyze_image_with_vision(args['url'], question)
                    
                    elif func_name == "chart_generator":
                        result = generate_chart_base64(
                            data_csv=args['data_csv'],
                            chart_type=args.get('chart_type', 'bar'),
                            x_col=args.get('x_col'),
                            y_col=args.get('y_col'),
                            title=args.get('title', 'Chart')
                        )
                    
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


def _extract_assistant_response(thread_id: str) -> Tuple[str, List[str], Dict[str, Any]]:
    """Fetch the latest assistant message and return text + image ids."""

    messages = make_openai_request(f"threads/{thread_id}/messages", method="GET")
    answer_text = ""
    attachments: List[str] = []

    for msg in messages.get("data", []):
        if msg.get("role") != "assistant":
            continue
        for content_part in msg.get("content", []):
            if content_part["type"] == "text" and not answer_text:
                answer_text = content_part["text"]["value"].strip()
            elif content_part["type"] == "image_file":
                attachments.append(content_part["image_file"]["file_id"])
        if answer_text:
            break

    return answer_text, attachments, messages

# --- MAIN FLOW ---

def solve_quiz_question(question_prompt: str, *, verbose: bool = True) -> Dict[str, Any]:
    """Execute the autonomous agent pipeline and return the assistant's answer."""

    result: Dict[str, Any] = {
        "status": "error",
        "answer": None,
        "thread_id": None,
        "run_id": None,
        "attachments": [],
    }

    try:
        assistant = create_assistant()
        assistant_id = assistant['id']
        if verbose:
            print("Creating Run...")

        run_payload = {
            "assistant_id": assistant_id,
            "thread": {"messages": [{"role": "user", "content": question_prompt}]},
            "model": MODEL_NAME,
        }
        run = make_openai_request("threads/runs", method="POST", data=run_payload)
        result.update({"thread_id": run["thread_id"], "run_id": run["id"]})

        final_run = process_run_loop(run['thread_id'], run['id'])
        final_status = final_run.get('status') if final_run else 'failed'
        result["status"] = final_status

        if final_status == 'completed':
            answer_text, attachments, messages = _extract_assistant_response(run['thread_id'])
            result.update({
                "answer": answer_text,
                "attachments": attachments,
                "messages": messages,
            })
            if verbose:
                print("\n--- Final AI Message ---")
                if answer_text:
                    print(answer_text)
                if attachments:
                    for img in attachments:
                        print(f"[Image File Generated: {img}]")
        else:
            result["error"] = final_run.get('last_error') if final_run else 'Unknown failure'
            if verbose:
                print(f"Run ended with status {final_status}: {result.get('error')}")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        if verbose:
            print(f"\n[Fatal Error] {e}")

    return result

if __name__ == "__main__":
    if "YOUR_OPENAI_SK_KEY_HERE" in OPENAI_API_KEY:
        print("⚠️  Please set OPENAI_API_KEY in your .env file.")

    email, secret = get_user_credentials()
    
    prompt = (
        f"solve https://tds-llm-analysis.s-anand.net/demo, "
        f"When posting the JSON, include 'student_email': '{email}' and 'secret_code': '{secret}' in the payload."
        f"keep checking any urls provided until you get the final answer. a succesful response might cointain urls with additional problems"
    )



    response = solve_quiz_question(prompt)
    print("\nResponse summary:")
    print(json.dumps({k: v for k, v in response.items() if k != "messages"}, indent=2))