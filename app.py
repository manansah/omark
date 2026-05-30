import os
import sys
import queue
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

# Apply DPI awareness to ensure high-resolution rendering on Windows screens
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# ==========================================
# STYLING CONSTANTS (Sleek Dark Theme)
# ==========================================
BG_MAIN = "#121214"          # Deep dark charcoal for window bg
BG_CARD = "#1a1a24"          # Dark blue-grey for sections/cards
BG_INPUT = "#27273a"         # Input background
FG_PRIMARY = "#f3f4f6"       # Bright grey/white for labels
FG_SECONDARY = "#9ca3af"     # Medium grey for descriptive text and hints
ACCENT_PRIMARY = "#6366f1"   # Indigo for start action
ACCENT_HOVER = "#4f46e5"     # Darker indigo for hover state
ACCENT_ACTIVE = "#4338ca"    # Click state
ACCENT_MUTED = "#37374e"      # Muted grey-blue for secondary actions (e.g. browse)
ACCENT_MUTED_HOVER = "#4a4a68"
ACCENT_DANGER = "#dc2626"    # Red for clear/stop action
ACCENT_DANGER_HOVER = "#b91c1c"
ACCENT_WARN = "#d97706"      # Orange/Amber for pause
ACCENT_WARN_HOVER = "#b45309"

FONT_TITLE = ("Segoe UI", 14, "bold")
FONT_SUBTITLE = ("Segoe UI", 9)
FONT_HEADING = ("Segoe UI", 11, "bold")
FONT_BODY = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_CONSOLE = ("Consolas", 10)

# ==========================================
# CUSTOM WIDGET HELPERS
# ==========================================
def create_flat_button(parent, text, command, bg=ACCENT_PRIMARY, fg=FG_PRIMARY, 
                       hover_bg=ACCENT_HOVER, active_bg=ACCENT_ACTIVE, 
                       font=FONT_BOLD, width=None, **kwargs):
    """Creates a beautiful flat button with custom hover states."""
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=fg,
        font=font,
        relief="flat",
        bd=0,
        cursor="hand2",
        padx=12,
        pady=6,
        width=width,
        **kwargs
    )
    # Register hover event bindings
    btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg) if btn['state'] == tk.NORMAL else None)
    btn.bind("<Leave>", lambda e: btn.config(bg=bg) if btn['state'] == tk.NORMAL else None)
    return btn

def create_styled_entry(parent, textvariable=None, width=30, **kwargs):
    """Creates an Entry widget with dark background, flat style, and highlight borders."""
    border_frame = tk.Frame(parent, bg="#4b5563", bd=0, padx=1, pady=1)
    
    entry = tk.Entry(
        border_frame,
        textvariable=textvariable,
        width=width,
        bg=BG_INPUT,
        fg=FG_PRIMARY,
        insertbackground=FG_PRIMARY,  # Caret cursor color
        relief="flat",
        bd=0,
        font=FONT_BODY,
        highlightthickness=4,
        highlightbackground=BG_INPUT,
        highlightcolor=BG_INPUT,
        **kwargs
    )
    entry.pack(fill="both", expand=True)
    
    # Visual focus ring indicators
    entry.bind("<FocusIn>", lambda e: border_frame.config(bg=ACCENT_PRIMARY))
    entry.bind("<FocusOut>", lambda e: border_frame.config(bg="#4b5563"))
    
    return border_frame, entry

# ==========================================
# BACKGROUND WORKER CONVERSION ENGINE
# ==========================================
def conversion_worker(endpoint, model, files_list, output_dir, log_queue, 
                      pause_event, stop_event, llm_prompt, force_ocr, pdf_scale):
    """
    Executes the batch document-to-markdown conversion inside a background thread.
    Checks pause_event and stop_event cooperatively between file boundaries.
    """
    def log(level, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_queue.put(("LOG", level, f"[{timestamp}] [{level}] {message}\n"))

    log("START", "Initializing OpenAI client & MarkItDown...")
    
    try:
        from openai import OpenAI
        from markitdown import MarkItDown
    except ImportError as e:
        log("ERROR", f"Required libraries not installed: {str(e)}.")
        log("ERROR", "Please run: pip install openai markitdown")
        log_queue.put(("STATUS", "IDLE"))
        return
        
    try:
        # Connect to Ollama API via OpenAI-compatible endpoint
        client = OpenAI(base_url=endpoint, api_key="ollama")
        md = MarkItDown(enable_plugins=True, llm_client=client, llm_model=model)
    except Exception as e:
        log("ERROR", f"Failed to initialize MarkItDown: {str(e)}")
        log_queue.put(("STATUS", "IDLE"))
        return

    # Ensure output directory exists (auto-created if not present)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        log("ERROR", f"Failed to create output directory: {str(e)}")
        log_queue.put(("STATUS", "IDLE"))
        return

    total_files = len(files_list)
    successful_conversions = 0

    for index, filepath in enumerate(files_list, 1):
        # Cooperative check: Did the user hit Stop?
        if stop_event.is_set():
            log("INFO", "Operation aborted by user.")
            log_queue.put(("STATUS", "IDLE"))
            return

        # Cooperative check: Did the user hit Pause?
        if not pause_event.is_set():
            log("INFO", "Operation paused. Waiting for resume...")
            log_queue.put(("STATUS", "PAUSED"))
            pause_event.wait()  # Block thread execution until pause_event is set
            
            # Re-check stop event in case the user clicked Stop while paused
            if stop_event.is_set():
                log("INFO", "Operation aborted by user.")
                log_queue.put(("STATUS", "IDLE"))
                return
                
            log("INFO", "Resuming batch operation...")
            log_queue.put(("STATUS", "RUNNING"))

        filename = os.path.basename(filepath)
        log("PROCESSING", f"File {index} of {total_files}: {filename}...")
        log_queue.put(("PROGRESS_BATCH", index, total_files))
        log_queue.put(("PROGRESS_FILE", "START", filename))
        
        # Guard block to prevent failures from crashing the entire batch queue
        try:
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"File path does not exist: {filepath}")
                
            is_pdf = filepath.lower().endswith(".pdf")
            
            # If visual OCR is forced for PDFs, render pages as images and process each page
            if is_pdf and force_ocr:
                log("INFO", f"Rendering PDF pages to images for visual OCR...")
                import pypdfium2 as pdfium
                
                with tempfile.TemporaryDirectory() as temp_dir:
                    doc = pdfium.PdfDocument(filepath)
                    total_pages = len(doc)
                    log("PROCESSING", f"Rendered {total_pages} page(s). Performing layout-aware visual OCR...")
                    
                    markdown_pages = []
                    for page_idx, page in enumerate(doc, 1):
                        # Cooperative cancellation check between pages
                        if stop_event.is_set():
                            log("INFO", "Operation aborted by user.")
                            log_queue.put(("STATUS", "IDLE"))
                            return
                            
                        # Check pause between pages
                        if not pause_event.is_set():
                            log("INFO", "Operation paused. Waiting for resume...")
                            log_queue.put(("STATUS", "PAUSED"))
                            pause_event.wait()
                            if stop_event.is_set():
                                log("INFO", "Operation aborted by user.")
                                log_queue.put(("STATUS", "IDLE"))
                                return
                            log("INFO", "Resuming batch operation...")
                            log_queue.put(("STATUS", "RUNNING"))

                        log("PROCESSING", f"Processing page {page_idx} of {total_pages}...")
                        
                        # Render page at specified scale (lower scale runs faster)
                        bitmap = page.render(scale=pdf_scale)
                        pil_img = bitmap.to_pil()
                        
                        temp_image_path = os.path.join(temp_dir, f"page_{page_idx}.png")
                        pil_img.save(temp_image_path)
                        
                        # Call MarkItDown with custom transcription prompt
                        page_result = md.convert(temp_image_path, llm_prompt=llm_prompt)
                        markdown_pages.append(page_result.text_content)
                    
                    # Combine page conversions with page delimiters
                    full_text = "\n\n--\n\n".join(markdown_pages)
                    
                    base_name = Path(filename).stem
                    dest_file = os.path.join(output_dir, f"{base_name}.md")
                    with open(dest_file, "w", encoding="utf-8") as f:
                        f.write(full_text)
            else:
                # Perform standard document extraction (MarkItDown decides based on format)
                # Pass prompt to be utilized if LLM/vision fallback path is invoked
                result = md.convert(filepath, llm_prompt=llm_prompt)
                
                base_name = Path(filename).stem
                dest_file = os.path.join(output_dir, f"{base_name}.md")
                with open(dest_file, "w", encoding="utf-8") as f:
                    f.write(result.text_content)
                
            successful_conversions += 1
            log("SUCCESS", f"Saved: {dest_file}")
            
        except Exception as e:
            # Captures Ollama offline, VRAM out-of-memory, or document parsing errors gracefully
            log("ERROR", f"Failed to convert '{filename}': {str(e)}")
            
        finally:
            log_queue.put(("PROGRESS_FILE", "STOP", filename))
            
    log("INFO", f"Batch conversion complete. Successfully processed {successful_conversions} of {total_files} files.")
    log_queue.put(("STATUS", "IDLE"))

# ==========================================
# MAIN APPLICATION INTERFACE
# ==========================================
class MarkItDownApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Local Document to Markdown Converter")
        self.root.geometry("800x820")
        self.root.configure(bg=BG_MAIN)
        self.root.minsize(700, 700)
        
        self.selected_files = []
        self.log_queue = queue.Queue()
        
        # Core threading events for flow control
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.app_state = "IDLE"  # Can be IDLE, RUNNING, PAUSED, STOPPING
        
        self.setup_ui()
        self.poll_queue()
        
    def setup_ui(self):
        # Configure layout grids
        self.root.grid_rowconfigure(3, weight=1)  # Allow console area to expand
        self.root.grid_columnconfigure(0, weight=1)
        
        # ----------------- HEADER AREA -----------------
        header_frame = tk.Frame(self.root, bg=BG_MAIN, pady=10, padx=20)
        header_frame.grid(row=0, column=0, sticky="ew")
        header_frame.columnconfigure(0, weight=1)
        
        lbl_title = tk.Label(header_frame, text="MARKITDOWN BATCH CONVERTER", font=FONT_TITLE, fg=ACCENT_PRIMARY, bg=BG_MAIN, anchor="w")
        lbl_title.grid(row=0, column=0, sticky="w")
        
        lbl_subtitle = tk.Label(
            header_frame, 
            text="Convert PDFs, Word files, Presentations, Images and Spreadsheets to Markdown via local Qwen3.5 OCR.",
            font=FONT_SUBTITLE, fg=FG_SECONDARY, bg=BG_MAIN, anchor="w"
        )
        lbl_subtitle.grid(row=1, column=0, sticky="w")
        
        # ----------------- CONFIG & PATHS AREA -----------------
        cards_frame = tk.Frame(self.root, bg=BG_MAIN, padx=20)
        cards_frame.grid(row=1, column=0, sticky="ew")
        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)
        
        # -- CARD 1: OLLAMA CONFIGURATION --
        cfg_card = tk.LabelFrame(cards_frame, text=" Ollama Settings ", font=FONT_HEADING, fg=FG_PRIMARY, bg=BG_CARD, bd=1, relief="flat", padx=12, pady=12)
        cfg_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        cfg_card.columnconfigure(1, weight=1)
        
        tk.Label(cfg_card, text="Ollama Endpoint:", font=FONT_BODY, fg=FG_PRIMARY, bg=BG_CARD).grid(row=0, column=0, sticky="w", pady=4)
        self.endpoint_var = tk.StringVar(value="http://localhost:11434/v1")
        border_end, self.ent_endpoint = create_styled_entry(cfg_card, textvariable=self.endpoint_var)
        border_end.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)
        
        tk.Label(cfg_card, text="Vision Model:", font=FONT_BODY, fg=FG_PRIMARY, bg=BG_CARD).grid(row=1, column=0, sticky="w", pady=4)
        self.model_var = tk.StringVar(value="qwen3.5:9b")
        border_mod, self.ent_model = create_styled_entry(cfg_card, textvariable=self.model_var)
        border_mod.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)
        
        # Text prompt for OCR tuning
        tk.Label(cfg_card, text="OCR Prompt:", font=FONT_BODY, fg=FG_PRIMARY, bg=BG_CARD).grid(row=2, column=0, sticky="nw", pady=4)
        prompt_border = tk.Frame(cfg_card, bg="#4b5563", bd=0, padx=1, pady=1)
        prompt_border.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)
        
        self.txt_prompt = tk.Text(
            prompt_border,
            height=3,
            bg=BG_INPUT,
            fg=FG_PRIMARY,
            insertbackground=FG_PRIMARY,
            font=FONT_BODY,
            relief="flat",
            bd=0,
            wrap="word",
            highlightthickness=0
        )
        self.txt_prompt.pack(fill="both", expand=True)
        default_prompt = (
            "Transcribe all text from this image. The document contains mixed English and Hindi (Devanagari script) text. "
            "Transcribe Devanagari words exactly as Devanagari text, and English words exactly as English text. "
            "Maintain the original layout and format using Markdown. Do not summarize or translate. Output ONLY the transcribed text."
        )
        self.txt_prompt.insert("1.0", default_prompt)
        self.txt_prompt.bind("<FocusIn>", lambda e: prompt_border.config(bg=ACCENT_PRIMARY))
        self.txt_prompt.bind("<FocusOut>", lambda e: prompt_border.config(bg="#4b5563"))
        
        # Checkbutton to force visual OCR rendering on PDFs
        self.force_ocr_var = tk.BooleanVar(value=True)
        self.chk_force_ocr = tk.Checkbutton(
            cfg_card,
            text="Force Visual OCR (Render PDF to images)",
            variable=self.force_ocr_var,
            font=FONT_BODY,
            fg=FG_PRIMARY,
            bg=BG_CARD,
            activeforeground=FG_PRIMARY,
            activebackground=BG_CARD,
            selectcolor=BG_INPUT,
            bd=0,
            relief="flat"
        )
        tk.Label(cfg_card, text="OCR Quality/Speed:", font=FONT_BODY, fg=FG_PRIMARY, bg=BG_CARD).grid(row=3, column=0, sticky="w", pady=4)
        self.quality_var = tk.StringVar(value="Balanced (1.4x)")
        
        self.cmb_quality = ttk.Combobox(
            cfg_card, 
            textvariable=self.quality_var, 
            values=["Fast (1.0x)", "Balanced (1.4x)", "High (2.0x)"],
            state="readonly",
            font=FONT_BODY
        )
        self.cmb_quality.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)
        
        self.chk_force_ocr.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        
        # -- CARD 2: FILE SELECTION & OUTPUTS --
        io_card = tk.LabelFrame(cards_frame, text=" Paths & Files ", font=FONT_HEADING, fg=FG_PRIMARY, bg=BG_CARD, bd=1, relief="flat", padx=12, pady=12)
        io_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        io_card.columnconfigure(1, weight=1)
        
        # Files display & buttons
        tk.Label(io_card, text="Selected Files:", font=FONT_BODY, fg=FG_PRIMARY, bg=BG_CARD).grid(row=0, column=0, sticky="w", pady=4)
        
        btn_files_frame = tk.Frame(io_card, bg=BG_CARD)
        btn_files_frame.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)
        btn_files_frame.columnconfigure(0, weight=1)
        
        self.btn_select_files = create_flat_button(
            btn_files_frame, "Browse Files...", self.select_files,
            bg=ACCENT_MUTED, hover_bg=ACCENT_MUTED_HOVER
        )
        self.btn_select_files.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        
        self.btn_clear_files = create_flat_button(
            btn_files_frame, "Clear", self.clear_files,
            bg=ACCENT_DANGER, hover_bg=ACCENT_DANGER_HOVER, width=6
        )
        self.btn_clear_files.grid(row=0, column=1, sticky="e")
        
        # Selected listbox
        list_frame = tk.Frame(io_card, bg="#4b5563", bd=0, padx=1, pady=1)
        list_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        
        self.lst_files = tk.Listbox(
            list_frame, bg=BG_INPUT, fg=FG_PRIMARY, selectbackground=ACCENT_PRIMARY,
            selectforeground=FG_PRIMARY, font=FONT_BODY, height=4, relief="flat", bd=0, highlightthickness=0
        )
        self.lst_files.pack(fill="x", side="left", expand=True)
        
        lst_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.lst_files.yview)
        lst_scroll.pack(fill="y", side="right")
        self.lst_files.config(yscrollcommand=lst_scroll.set)
        
        # Output directory selection
        tk.Label(io_card, text="Output Folder:", font=FONT_BODY, fg=FG_PRIMARY, bg=BG_CARD).grid(row=2, column=0, sticky="w", pady=4)
        
        out_frame = tk.Frame(io_card, bg=BG_CARD)
        out_frame.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)
        out_frame.columnconfigure(0, weight=1)
        
        self.output_var = tk.StringVar()
        border_out, self.ent_output = create_styled_entry(out_frame, textvariable=self.output_var)
        border_out.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        
        self.btn_browse_output = create_flat_button(
            out_frame, "...", self.select_output_dir,
            bg=ACCENT_MUTED, hover_bg=ACCENT_MUTED_HOVER, width=3
        )
        self.btn_browse_output.grid(row=0, column=1, sticky="e")
        
        # ----------------- PROGRESS & CONVERSION CONTROL PANEL -----------------
        control_frame = tk.Frame(self.root, bg=BG_MAIN, padx=20, pady=10)
        control_frame.grid(row=2, column=0, sticky="ew")
        control_frame.columnconfigure(0, weight=1)
        
        # -- Sub-Panel 1: Progress Indicators --
        progress_card = tk.LabelFrame(control_frame, text=" Conversion Progress ", font=FONT_HEADING, fg=FG_PRIMARY, bg=BG_CARD, bd=1, relief="flat", padx=12, pady=8)
        progress_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        progress_card.columnconfigure(0, weight=1)
        
        # Custom styling for ttk.Progressbar
        progressbar_style = ttk.Style()
        progressbar_style.theme_use('default')
        progressbar_style.configure("TProgressbar", 
                                    thickness=6, 
                                    troughcolor=BG_MAIN, 
                                    background=ACCENT_PRIMARY,
                                    borderwidth=0)
        
        # Progress Bar 1: Overall batch progress
        self.lbl_progress_batch = tk.Label(progress_card, text="Overall Batch Progress: Idle", font=FONT_BODY, fg=FG_PRIMARY, bg=BG_CARD, anchor="w")
        self.lbl_progress_batch.grid(row=0, column=0, sticky="w", pady=(2, 2))
        self.progress_bar_overall = ttk.Progressbar(progress_card, style="TProgressbar", mode="determinate", value=0)
        self.progress_bar_overall.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        
        # Progress Bar 2: Active file progress
        self.lbl_progress_file = tk.Label(progress_card, text="Active File OCR Status: Idle", font=FONT_BODY, fg=FG_PRIMARY, bg=BG_CARD, anchor="w")
        self.lbl_progress_file.grid(row=2, column=0, sticky="w", pady=(2, 2))
        self.progress_bar_file = ttk.Progressbar(progress_card, style="TProgressbar", mode="determinate", value=0)
        self.progress_bar_file.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        
        # -- Sub-Panel 2: Control Button Grid --
        btn_grid = tk.Frame(control_frame, bg=BG_MAIN)
        btn_grid.grid(row=1, column=0, sticky="ew")
        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=1)
        btn_grid.columnconfigure(2, weight=1)
        
        self.btn_start = create_flat_button(
            btn_grid, "Start Conversion", self.start_conversion,
            bg=ACCENT_PRIMARY, hover_bg=ACCENT_HOVER, active_bg=ACCENT_ACTIVE,
            font=("Segoe UI", 10, "bold")
        )
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        self.btn_pause = create_flat_button(
            btn_grid, "Pause", self.pause_conversion,
            bg=ACCENT_MUTED, hover_bg=ACCENT_MUTED_HOVER, active_bg=ACCENT_WARN,
            font=("Segoe UI", 10, "bold")
        )
        self.btn_pause.grid(row=0, column=1, sticky="ew", padx=5)
        
        self.btn_stop = create_flat_button(
            btn_grid, "Stop", self.stop_conversion,
            bg=ACCENT_MUTED, hover_bg=ACCENT_MUTED_HOVER, active_bg=ACCENT_DANGER,
            font=("Segoe UI", 10, "bold")
        )
        self.btn_stop.grid(row=0, column=2, sticky="ew", padx=(5, 0))
        
        # Apply initial disabled/enabled button states
        self.set_ui_state("IDLE")
        
        # ----------------- LOGGING CONSOLE -----------------
        console_frame = tk.LabelFrame(
            self.root, text=" Live Activity Console ", font=FONT_HEADING, 
            fg=FG_PRIMARY, bg=BG_MAIN, bd=1, relief="flat", padx=20, pady=10
        )
        console_frame.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 20))
        console_frame.columnconfigure(0, weight=1)
        console_frame.rowconfigure(0, weight=1)
        
        self.txt_console = ScrolledText(
            console_frame, bg=BG_MAIN, fg=FG_PRIMARY, insertbackground=FG_PRIMARY,
            font=FONT_CONSOLE, wrap="word", relief="flat", bd=0, highlightthickness=1,
            highlightbackground="#4b5563", highlightcolor=ACCENT_PRIMARY,
            height=12
        )
        self.txt_console.grid(row=0, column=0, sticky="nsew")
        
        # Setup specific tags for logs color-coding
        self.txt_console.tag_config("START", foreground="#60a5fa")       # Light Blue
        self.txt_console.tag_config("PROCESSING", foreground="#a78bfa")  # Light Purple
        self.txt_console.tag_config("SUCCESS", foreground="#34d399")     # Emerald Green
        self.txt_console.tag_config("ERROR", foreground="#f87171")       # Soft Red
        self.txt_console.tag_config("INFO", foreground="#38bdf8")        # Cyan/Sky
        self.txt_console.tag_config("NORMAL", foreground=FG_PRIMARY)     # White/Grey
        
        # Warm greeting log
        self.write_log("INFO", "Application initialized. Please select input documents and click 'Start Conversion'.\n")

    # ==========================================
    # COMPONENT TRIGGER HANDLERS
    # ==========================================
    def select_files(self):
        """Allows user to select multiple compatible documents for processing."""
        file_types = [
            ("All Supported Formats", "*.pdf;*.docx;*.xlsx;*.pptx;*.png;*.jpg;*.jpeg"),
            ("PDF Documents", "*.pdf"),
            ("Word Documents", "*.docx"),
            ("Excel Spreadsheets", "*.xlsx"),
            ("PowerPoint Presentations", "*.pptx"),
            ("Images", "*.png;*.jpg;*.jpeg")
        ]
        files = filedialog.askopenfilenames(
            title="Select Documents for Batch Markdown Conversion",
            filetypes=file_types
        )
        if files:
            for f in files:
                if f not in self.selected_files:
                    self.selected_files.append(f)
                    self.lst_files.insert(tk.END, os.path.basename(f))
            self.update_progress_labels_idle()

    def clear_files(self):
        """Clears the queue of selected files."""
        self.selected_files.clear()
        self.lst_files.delete(0, tk.END)
        self.update_progress_labels_idle()

    def select_output_dir(self):
        """Displays directory selection dialog for the conversion output path."""
        selected_dir = filedialog.askdirectory(title="Select Destination Folder")
        if selected_dir:
            self.output_var.set(selected_dir)

    def update_progress_labels_idle(self):
        """Helper to reflect the current count of loaded files when in idle state."""
        count = len(self.selected_files)
        if count == 0:
            self.lbl_progress_batch.config(text="Overall Batch Progress: Idle")
        else:
            self.lbl_progress_batch.config(text=f"Overall Batch Progress: {count} file(s) loaded")

    # ==========================================
    # FLOW CONTROL OPERATIONS (START/PAUSE/STOP)
    # ==========================================
    def start_conversion(self):
        """Starts the conversion execution inside a non-blocking background thread, or resumes if paused."""
        if self.app_state == "PAUSED":
            # Unblock the worker thread
            self.pause_event.set()
            self.set_ui_state("RUNNING")
            return
            
        if self.app_state != "IDLE":
            return
            
        if not self.selected_files:
            messagebox.showwarning("No Files", "Please select one or more files to convert first.")
            return

        endpoint = self.endpoint_var.get().strip()
        model = self.model_var.get().strip()
        
        if not endpoint:
            messagebox.showwarning("Invalid Input", "Ollama endpoint URL cannot be blank.")
            return

        # Auto-append /v1 if missing for Ollama OpenAI compatibility
        if not endpoint.endswith("/v1") and not endpoint.endswith("/v1/"):
            sanitized_endpoint = endpoint.rstrip("/") + "/v1"
            self.write_log("INFO", f"Auto-sanitized endpoint: {endpoint} -> {sanitized_endpoint}\n")
            endpoint = sanitized_endpoint

        if not model:
            messagebox.showwarning("Invalid Input", "Ollama model name cannot be blank.")
            return

        # Determine output folder path. Fall back to "./outputs" in script directory if left blank
        output_dir = self.output_var.get().strip()
        if not output_dir:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, "outputs")
            self.output_var.set(output_dir)
            self.write_log("INFO", f"Defaulted output directory to: {output_dir}\n")

        # Get visual OCR preferences
        llm_prompt = self.txt_prompt.get("1.0", tk.END).strip()
        force_ocr = self.force_ocr_var.get()

        # Initialize thread events
        self.pause_event.set()      # Unpaused by default
        self.stop_event.clear()     # Not stopped by default
        
        # Reset progress bar widgets
        self.progress_bar_overall.config(value=0)
        self.progress_bar_file.config(value=0)
        
        self.set_ui_state("RUNNING")
        
        # Get render scale multiplier
        quality_str = self.quality_var.get()
        if "Fast" in quality_str:
            pdf_scale = 1.0
        elif "High" in quality_str:
            pdf_scale = 2.0
        else:
            pdf_scale = 1.4

        # Spin up a worker thread to perform conversion in the background,
        # ensuring the main tkinter thread remains interactive and window-draggable.
        worker_thread = threading.Thread(
            target=conversion_worker,
            args=(endpoint, model, self.selected_files, output_dir, self.log_queue, 
                  self.pause_event, self.stop_event, llm_prompt, force_ocr, pdf_scale),
            daemon=True
        )
        worker_thread.start()

    def pause_conversion(self):
        """Signals the worker thread to pause conversion at the next file boundary."""
        if self.app_state == "RUNNING":
            self.pause_event.clear()  # This will block the thread on wait()
            self.write_log("INFO", "Pause requested. Halting after active file completes...\n")

    def stop_conversion(self):
        """Signals the worker thread to cancel conversion."""
        if self.app_state in ("RUNNING", "PAUSED"):
            self.stop_event.set()
            self.pause_event.set()  # Unblock thread if paused so it immediately checks stop_event and exits
            self.write_log("INFO", "Stop requested. Terminating after active file completes...\n")
            self.set_ui_state("STOPPING")

    # ==========================================
    # STATE AND LAYOUT STATE MACHINE
    # ==========================================
    def set_ui_state(self, state):
        """Toggles interface states and buttons depending on the flow state machine."""
        self.app_state = state
        
        is_idle = (state == "IDLE")
        is_running = (state == "RUNNING")
        is_paused = (state == "PAUSED")
        is_stopping = (state == "STOPPING")
        
        # Toggle inputs
        entry_state = tk.NORMAL if is_idle else tk.DISABLED
        self.btn_select_files.config(state=entry_state)
        self.btn_clear_files.config(state=entry_state)
        self.btn_browse_output.config(state=entry_state)
        self.ent_endpoint.config(state=entry_state)
        self.ent_model.config(state=entry_state)
        self.ent_output.config(state=entry_state)
        self.txt_prompt.config(state=entry_state)
        self.chk_force_ocr.config(state=entry_state)
        self.cmb_quality.config(state="readonly" if is_idle else tk.DISABLED)
        
        # Toggle control button configurations and background colors
        if is_idle:
            self.btn_start.config(text="Start Conversion", bg=ACCENT_PRIMARY, state=tk.NORMAL)
            self.btn_pause.config(text="Pause", bg=ACCENT_MUTED, state=tk.DISABLED)
            self.btn_stop.config(text="Stop", bg=ACCENT_MUTED, state=tk.DISABLED)
            # Reset progress representations
            self.lbl_progress_file.config(text="Active File OCR Status: Idle")
            self.progress_bar_file.config(mode="determinate", value=0)
            self.progress_bar_file.stop()
            self.update_progress_labels_idle()
            
        elif is_running:
            self.btn_start.config(text="Start Conversion", bg=ACCENT_MUTED, state=tk.DISABLED)
            self.btn_pause.config(text="Pause", bg=ACCENT_WARN, state=tk.NORMAL)
            self.btn_pause.bind("<Enter>", lambda e: self.btn_pause.config(bg=ACCENT_WARN_HOVER))
            self.btn_pause.bind("<Leave>", lambda e: self.btn_pause.config(bg=ACCENT_WARN))
            self.btn_stop.config(text="Stop", bg=ACCENT_DANGER, state=tk.NORMAL)
            self.btn_stop.bind("<Enter>", lambda e: self.btn_stop.config(bg=ACCENT_DANGER_HOVER))
            self.btn_stop.bind("<Leave>", lambda e: self.btn_stop.config(bg=ACCENT_DANGER))
            
        elif is_paused:
            self.btn_start.config(text="Resume", bg=ACCENT_PRIMARY, state=tk.NORMAL)
            self.btn_pause.config(text="Paused", bg=ACCENT_MUTED, state=tk.DISABLED)
            self.btn_stop.config(text="Stop", bg=ACCENT_DANGER, state=tk.NORMAL)
            self.btn_stop.bind("<Enter>", lambda e: self.btn_stop.config(bg=ACCENT_DANGER_HOVER))
            self.btn_stop.bind("<Leave>", lambda e: self.btn_stop.config(bg=ACCENT_DANGER))
            # Pause the active file's progress bar animation
            self.progress_bar_file.stop()
            
        elif is_stopping:
            self.btn_start.config(text="Start Conversion", bg=ACCENT_MUTED, state=tk.DISABLED)
            self.btn_pause.config(text="Pause", bg=ACCENT_MUTED, state=tk.DISABLED)
            self.btn_stop.config(text="Stopping...", bg=ACCENT_MUTED, state=tk.DISABLED)

    def write_log(self, level, text):
        """Thread-safely appends color-coded timestamp messages to the ScrolledText console."""
        self.txt_console.config(state=tk.NORMAL)
        self.txt_console.insert(tk.END, text, level)
        self.txt_console.see(tk.END)
        self.txt_console.config(state=tk.DISABLED)

    def poll_queue(self):
        """
        Polls the log queue for progress and state updates sent from the background worker.
        Reschedules itself dynamically every 100ms in the main loop.
        """
        try:
            while True:
                data = self.log_queue.get_nowait()
                msg_type = data[0]
                
                if msg_type == "LOG":
                    level, text = data[1], data[2]
                    self.write_log(level, text)
                    
                elif msg_type == "STATUS":
                    state = data[1]
                    self.set_ui_state(state)
                        
                elif msg_type == "PROGRESS_BATCH":
                    curr, total = data[1], data[2]
                    percentage = (curr / total) * 100
                    self.progress_bar_overall.config(value=percentage)
                    self.lbl_progress_batch.config(text=f"Overall Batch Progress: File {curr} of {total} completed ({int(percentage)}%)")
                    
                elif msg_type == "PROGRESS_FILE":
                    event_type, filename = data[1], data[2]
                    if event_type == "START":
                        self.lbl_progress_file.config(text=f"Active File OCR Status: Converting '{filename}'...")
                        # Run the file progress bar in indeterminate mode to show continuous GPU/OCR activity
                        self.progress_bar_file.config(mode="indeterminate")
                        self.progress_bar_file.start(12)
                    elif event_type == "STOP":
                        self.progress_bar_file.stop()
                        self.progress_bar_file.config(mode="determinate", value=100)
                        self.lbl_progress_file.config(text=f"Active File OCR Status: Completed '{filename}'")
                        
                self.log_queue.task_done()
        except queue.Empty:
            pass
        finally:
            # Re-schedule the polling check
            self.root.after(100, self.poll_queue)

if __name__ == "__main__":
    root = tk.Tk()
    app = MarkItDownApp(root)
    root.mainloop()
