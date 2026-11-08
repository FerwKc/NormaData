import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from src.report import export_pdf
from src.remediation import build_remediation_plan, wrap_transaction
from src.rules import analyze_database
from src.sqlserver import SQLServerClient, SQLServerUnavailable
from src.history import AuditHistory


COLORS = {
    "canvas": "#080D18", "card": "#111A2B", "navy": "#0D1424", "navy_light": "#172238",
    "blue": "#36D7D2", "blue_hover": "#23B9C0", "sky": "#173342", "text": "#F3F7FF",
    "muted": "#93A4BE", "border": "#26354F", "success": "#4BD6A5", "warning": "#F2B562",
    "danger": "#FF6D7A", "white": "#F3F7FF", "violet": "#8C7CFF", "entry": "#0C1322",
}


class NormadataApp(tk.Tk):
    """NORMADATA Database Quality Studio para Microsoft SQL Server."""

    def __init__(self) -> None:
        super().__init__()
        self.title("NORMADATA | Database Quality Studio")
        self.geometry("1280x800")
        self.minsize(1080, 700)
        self.configure(bg=COLORS["canvas"])
        self.server_var = tk.StringVar(value=".\\SQLEXPRESS")
        self.port_var = tk.StringVar()
        self.user_var = tk.StringVar(value="sa")
        self.password_var = tk.StringVar()
        self.database_var = tk.StringVar()
        self.operation_mode = tk.StringVar(value="audit")
        self.status_var = tk.StringVar(value="Sin conexión")
        self.connection_verified = False
        self.is_busy = False
        self.client: SQLServerClient | None = None
        self.available_databases: dict[str, tuple] = {}
        self.loaded_tables = []
        self.current_result = None
        self.history = AuditHistory(Path(__file__).resolve().parents[1] / "output" / "historial.sqlite3")
        self.nav_buttons: dict[str, tk.Button] = {}
        self._spinner_angle = 0
        self._configure_style()
        self._build_shell()
        self._build_loading_overlay()
        self.after(300, self._hide_loading_overlay)
        self.after(340, self._show_connection)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["canvas"])
        style.configure("TEntry", padding=(11, 10), fieldbackground=COLORS["entry"], foreground=COLORS["text"], insertcolor=COLORS["blue"], bordercolor=COLORS["border"], lightcolor=COLORS["border"], darkcolor=COLORS["border"])
        style.configure("TCombobox", padding=(10, 9), fieldbackground=COLORS["entry"], foreground=COLORS["text"], background=COLORS["entry"], arrowcolor=COLORS["blue"], bordercolor=COLORS["border"])
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["entry"])], foreground=[("readonly", COLORS["text"])], selectbackground=[("readonly", COLORS["entry"])], selectforeground=[("readonly", COLORS["text"])])
        style.configure("Treeview", rowheight=40, font=("Segoe UI", 9), background=COLORS["entry"], fieldbackground=COLORS["entry"], foreground=COLORS["text"], borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), background="#19263B", foreground=COLORS["muted"], relief="flat")
        style.map("Treeview", background=[("selected", "#173E4D")], foreground=[("selected", COLORS["white"])])
        style.configure("Horizontal.TProgressbar", troughcolor="#1D2B42", background=COLORS["blue"], lightcolor=COLORS["blue"], darkcolor=COLORS["blue"], bordercolor="#1D2B42")
        style.configure("Switch.TCheckbutton", background=COLORS["card"], foreground=COLORS["text"], font=("Segoe UI Semibold", 10))

    def _build_shell(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        sidebar = tk.Frame(self, bg=COLORS["navy"], width=252)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        brand = tk.Frame(sidebar, bg=COLORS["navy"]); brand.pack(fill="x", padx=24, pady=(27, 0))
        tk.Label(brand, text="N", bg=COLORS["blue"], fg=COLORS["navy"], font=("Segoe UI Black", 15), padx=10, pady=5).pack(side="left")
        tk.Label(brand, text="NORMADATA", bg=COLORS["navy"], fg=COLORS["white"], font=("Segoe UI Semibold", 16)).pack(side="left", padx=9)
        tk.Label(sidebar, text="DATABASE QUALITY STUDIO", bg=COLORS["navy"], fg=COLORS["muted"], font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=26, pady=(12, 0))
        tk.Frame(sidebar, bg=COLORS["border"], height=1).pack(fill="x", padx=26, pady=25)
        tk.Label(sidebar, text="WORKFLOW", bg=COLORS["navy"], fg=COLORS["muted"], font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=26, pady=(0, 8))
        for key, number, label in (("connection", "01", "Conexión"), ("selection", "02", "Alcance del análisis"), ("results", "03", "Resultados"), ("history", "04", "Historial")):
            button = tk.Button(sidebar, text=f"{number}    {label}", command=lambda item=key: self._navigate(item), anchor="w", relief="flat", borderwidth=0, padx=16, pady=13, bg=COLORS["navy"], fg=COLORS["muted"], activebackground=COLORS["navy_light"], activeforeground=COLORS["white"], font=("Segoe UI Semibold", 10), cursor="hand2")
            button.pack(fill="x", padx=14, pady=2)
            self.nav_buttons[key] = button
        footer = tk.Frame(sidebar, bg="#121F34", highlightthickness=1, highlightbackground=COLORS["border"])
        footer.pack(side="bottom", fill="x", padx=16, pady=18)
        tk.Label(footer, text="●  SYSTEM STATUS", bg="#121F34", fg=COLORS["blue"], font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=12, pady=(11, 2))
        tk.Label(footer, textvariable=self.status_var, wraplength=190, justify="left", bg="#121F34", fg=COLORS["white"], font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(0, 11))
        main = tk.Frame(self, bg=COLORS["canvas"])
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        self._build_topbar(main)
        self.content = tk.Frame(main, bg=COLORS["canvas"])
        self.content.grid(row=1, column=0, sticky="nsew", padx=30, pady=(8, 30))
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

    def _build_topbar(self, parent) -> None:
        topbar = tk.Frame(parent, bg=COLORS["canvas"], height=92)
        topbar.grid(row=0, column=0, sticky="ew", padx=30, pady=(18, 0))
        topbar.grid_propagate(False)
        tk.Label(topbar, text="DATABASE QUALITY STUDIO", bg=COLORS["canvas"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(side="left", pady=26)
        self.mode_badge = tk.Label(topbar, text="AUDITORÍA · SOLO LECTURA", bg="#123F48", fg=COLORS["blue"], font=("Segoe UI Semibold", 8), padx=10, pady=6)
        self.mode_badge.pack(side="left", padx=14, pady=26)
        tk.Label(topbar, text="NORMADATA", bg=COLORS["canvas"], fg=COLORS["text"], font=("Segoe UI Semibold", 13)).pack(side="right", pady=26)

    def _build_loading_overlay(self) -> None:
        self.loading_overlay = tk.Frame(self, bg=COLORS["navy"])
        self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        card = tk.Frame(self.loading_overlay, bg=COLORS["navy"])
        card.place(relx=.5, rely=.5, anchor="center")
        tk.Label(card, text="NORMADATA", bg=COLORS["navy"], fg=COLORS["white"], font=("Segoe UI Semibold", 25)).pack()
        tk.Label(card, text="Preparando el entorno de auditoría", bg=COLORS["navy"], fg="#B9D7EE", font=("Segoe UI", 11)).pack(pady=(7, 18))
        self.start_progress = ttk.Progressbar(card, mode="indeterminate", length=250)
        self.start_progress.pack(); self.start_progress.start(12)

    def _hide_loading_overlay(self) -> None:
        self.start_progress.stop()
        self.loading_overlay.destroy()

    def _clear_content(self) -> tk.Frame:
        for widget in self.content.winfo_children(): widget.destroy()
        page = tk.Frame(self.content, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"])
        page.grid(row=0, column=0, sticky="nsew"); page.columnconfigure(0, weight=1)
        return page

    def _page_header(self, parent, title: str, subtitle: str, step: str) -> None:
        header = tk.Frame(parent, bg=COLORS["card"])
        header.grid(row=0, column=0, sticky="ew", padx=34, pady=(30, 0)); header.columnconfigure(0, weight=1)
        tk.Label(header, text=step, bg=COLORS["sky"], fg=COLORS["blue"], font=("Segoe UI Semibold", 9), padx=10, pady=5).grid(row=0, column=0, sticky="w")
        tk.Label(header, text=title, bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI Semibold", 25)).grid(row=1, column=0, sticky="w", pady=(14, 0))
        tk.Label(header, text=subtitle, bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 10), wraplength=790, justify="left").grid(row=2, column=0, sticky="w", pady=(5, 0))

    def _navigate(self, page: str) -> None:
        if self.is_busy: return
        if page == "selection" and not self.connection_verified:
            messagebox.showinfo("Conexión requerida", "Primero prepara o valida una conexión antes de definir el alcance."); return
        if page == "results" and self.current_result is None:
            messagebox.showinfo("Análisis requerido", "Primero selecciona las tablas y ejecuta el análisis."); return
        getattr(self, f"_show_{page}")()

    def _set_active(self, key: str) -> None:
        for name, button in self.nav_buttons.items():
            button.configure(bg="#183746" if name == key else COLORS["navy"], fg=COLORS["blue"] if name == key else COLORS["muted"])

    def _button(self, parent, text: str, command, primary: bool = False):
        return tk.Button(parent, text=text, command=command, relief="flat", borderwidth=0, cursor="hand2", padx=17, pady=11, font=("Segoe UI Semibold", 10), bg=COLORS["blue"] if primary else "#1A2940", fg=COLORS["navy"] if primary else COLORS["text"], activebackground=COLORS["blue_hover"] if primary else "#233652", activeforeground=COLORS["navy"] if primary else COLORS["white"])

    def _card(self, parent, title: str, subtitle: str | None = None) -> tk.Frame:
        card = tk.Frame(parent, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"])
        tk.Frame(card, bg=COLORS["violet"], height=2).pack(fill="x")
        tk.Label(card, text=title, bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI Semibold", 12)).pack(anchor="w", padx=20, pady=(18, 0))
        if subtitle: tk.Label(card, text=subtitle, bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=680, justify="left").pack(anchor="w", padx=20, pady=(4, 16))
        return card

    def _show_connection(self) -> None:
        self._set_active("connection"); page = self._clear_content()
        self._page_header(page, "Conectar SQL Server", "Configura el servidor y selecciona el nivel de acceso requerido para esta sesión.", "PASO 01 · CONEXIÓN")
        body = tk.Frame(page, bg=COLORS["card"]); body.grid(row=1, column=0, sticky="nsew", padx=34, pady=(26, 32)); body.columnconfigure(0, weight=3); body.columnconfigure(1, weight=2); page.rowconfigure(1, weight=1)
        form_card = self._card(body, "Datos de conexión", "Los datos se usan únicamente durante la sesión y nunca se almacenan."); form_card.grid(row=0, column=0, sticky="new", padx=(0, 14))
        form = tk.Frame(form_card, bg=COLORS["card"]); form.pack(fill="x", padx=20, pady=(0, 20)); form.columnconfigure(1, weight=1); self.form_entries = []
        for row, (label, variable, secret) in enumerate((("Servidor o instancia", self.server_var, False), ("Puerto (opcional)", self.port_var, False), ("Usuario SQL Server", self.user_var, False), ("Contraseña", self.password_var, True))):
            tk.Label(form, text=label, bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI Semibold", 9)).grid(row=row, column=0, sticky="w", pady=7)
            entry = ttk.Entry(form, textvariable=variable, show="•" if secret else ""); entry.grid(row=row, column=1, sticky="ew", padx=(18, 0), pady=7); self.form_entries.append(entry)
        actions = tk.Frame(form_card, bg=COLORS["card"]); actions.pack(fill="x", padx=20, pady=(0, 20))
        self._button(actions, "Validar conexión", self._test_connection).pack(side="left"); self._button(actions, "Continuar al análisis", self._continue_from_connection, primary=True).pack(side="left", padx=9)
        modes = self._card(body, "Modo de operación", "El nivel de acceso se aplica al crear la conexión."); modes.grid(row=0, column=1, sticky="new")
        self._mode_option(modes, "audit", "Modo Auditoría", "SOLO LECTURA · RECOMENDADO", "Consulta catálogos y muestras de datos. El ejecutor de cambios está bloqueado; los permisos efectivos dependen de la cuenta SQL.", COLORS["blue"])
        self._mode_option(modes, "remediation", "Remediación Activa", "DDL / DML · ALTO IMPACTO", "Permite analizar y ejecutar scripts transaccionales de corrección estructural sobre las tablas seleccionadas.", COLORS["warning"])

    def _feature(self, parent, title: str, text: str) -> None:
        item = tk.Frame(parent, bg=COLORS["card"]); item.pack(fill="x", padx=20, pady=(16, 0))
        tk.Label(item, text="●", bg=COLORS["card"], fg=COLORS["blue"], font=("Segoe UI", 11)).pack(side="left", anchor="n")
        copy = tk.Frame(item, bg=COLORS["card"]); copy.pack(side="left", fill="x", expand=True, padx=(8, 0))
        tk.Label(copy, text=title, bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI Semibold", 10)).pack(anchor="w")
        tk.Label(copy, text=text, bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=240, justify="left").pack(anchor="w", pady=(2, 0))

    def _mode_option(self, parent, value: str, title: str, badge: str, text: str, accent: str) -> None:
        option = tk.Frame(parent, bg=COLORS["entry"], highlightthickness=1, highlightbackground=COLORS["border"])
        option.pack(fill="x", padx=20, pady=(16, 0))
        radio = tk.Radiobutton(option, variable=self.operation_mode, value=value, command=self._operation_mode_changed, bg=COLORS["entry"], activebackground=COLORS["entry"], selectcolor=COLORS["navy"], fg=accent, activeforeground=accent, cursor="hand2")
        radio.pack(side="left", anchor="n", padx=(12, 4), pady=14)
        copy = tk.Frame(option, bg=COLORS["entry"]); copy.pack(side="left", fill="x", expand=True, padx=(4, 12), pady=12)
        tk.Label(copy, text=title, bg=COLORS["entry"], fg=COLORS["text"], font=("Segoe UI Semibold", 10)).pack(anchor="w")
        tk.Label(copy, text=badge, bg=COLORS["entry"], fg=accent, font=("Segoe UI Semibold", 8)).pack(anchor="w", pady=(3, 5))
        tk.Label(copy, text=text, bg=COLORS["entry"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=285, justify="left").pack(anchor="w")

    def _operation_mode_changed(self) -> None:
        self.connection_verified = False
        self.client = None
        self.available_databases = {}
        active = self.operation_mode.get() == "remediation"
        self.mode_badge.configure(
            text="REMEDIACIÓN ACTIVA" if active else "AUDITORÍA · SOLO LECTURA",
            bg="#4A2D16" if active else "#123F48",
            fg=COLORS["warning"] if active else COLORS["blue"],
        )
        self.status_var.set("Modo cambiado · valide nuevamente la conexión")

    def _continue_from_connection(self) -> None:
        if not self.connection_verified:
            messagebox.showinfo("Validación requerida", "Valida primero las credenciales de SQL Server."); return
        self._show_selection()

    def _test_connection(self) -> None:
        if self.is_busy: return
        if not self.server_var.get().strip() or not self.user_var.get().strip() or not self.password_var.get():
            messagebox.showwarning("Datos incompletos", "Ingresa servidor, usuario y contraseña para validar la conexión."); return
        self._set_busy(True, "Validando conexión segura con SQL Server…")
        threading.Thread(target=self._connect_worker, args=(self.server_var.get(), self.port_var.get(), self.user_var.get(), self.password_var.get(), self.operation_mode.get() == "audit"), daemon=True).start()

    def _connect_worker(self, server: str, port: str, user: str, password: str, read_only: bool) -> None:
        try:
            client = SQLServerClient(server, port, user, password, read_only=read_only); client.test_connection(); databases = client.list_databases(); self.after(0, lambda: self._connection_finished(client, databases, None))
        except (SQLServerUnavailable, Exception) as exc:
            self.after(0, lambda error=str(exc): self._connection_finished(None, [], error))

    def _connection_finished(self, client, databases, error: str | None) -> None:
        self._set_busy(False)
        if error:
            self.connection_verified = False; self.status_var.set("No fue posible validar la conexión"); messagebox.showerror("No se pudo conectar", error); return
        mode = "solo lectura" if self.operation_mode.get() == "audit" else "remediación activa"
        self.client = client; self.available_databases = {name: tuple() for name in databases}; self.connection_verified = True; self.status_var.set(f"SQL Server conectado · {len(databases)} bases · {mode}"); messagebox.showinfo("Conexión validada", f"La conexión se estableció en modo {mode}.")

    def _show_selection(self) -> None:
        self._set_active("selection"); page = self._clear_content()
        self._page_header(page, "Definir alcance", "Selecciona la base de datos y las tablas que participarán en el diagnóstico de normalización.", "PASO 02 · ALCANCE")
        body = tk.Frame(page, bg=COLORS["card"]); body.grid(row=1, column=0, sticky="nsew", padx=34, pady=(24, 32)); body.columnconfigure(0, weight=1); body.rowconfigure(1, weight=1); page.rowconfigure(1, weight=1)
        selector = tk.Frame(body, bg=COLORS["card"]); selector.grid(row=0, column=0, sticky="ew")
        tk.Label(selector, text="Base de datos", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI Semibold", 10)).pack(side="left")
        combo = ttk.Combobox(selector, textvariable=self.database_var, values=list(self.available_databases), state="readonly", width=42); combo.pack(side="left", padx=14); combo.bind("<<ComboboxSelected>>", lambda _event: self._load_tables_for_database())
        if not self.database_var.get() or self.database_var.get() not in self.available_databases: self.database_var.set(next(iter(self.available_databases), ""))
        self._button(selector, "Actualizar tablas", self._load_tables_for_database).pack(side="right")
        table_card = tk.Frame(body, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"]); table_card.grid(row=1, column=0, sticky="nsew", pady=(20, 0)); table_card.columnconfigure(0, weight=1); table_card.rowconfigure(1, weight=1)
        table_header = tk.Frame(table_card, bg=COLORS["card"])
        table_header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 16))
        tk.Label(table_header, text="Tablas disponibles", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI Semibold", 12)).pack(anchor="w")
        mode_text = "Solo se consultarán metadatos." if self.operation_mode.get() == "audit" else "Los cambios requerirán confirmación adicional en Resultados."
        tk.Label(table_header, text=f"Selecciona una o más tablas. {mode_text}", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))
        tree_wrap = tk.Frame(table_card, bg=COLORS["card"]); tree_wrap.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 8)); tree_wrap.columnconfigure(0, weight=1); tree_wrap.rowconfigure(0, weight=1)
        self.tables_tree = ttk.Treeview(tree_wrap, columns=("table", "columns", "pk"), show="headings", selectmode="extended")
        for key, label, width in (("table", "Tabla", 330), ("columns", "Columnas", 100), ("pk", "Clave primaria", 300)):
            self.tables_tree.heading(key, text=label); self.tables_tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tables_tree.yview); self.tables_tree.configure(yscrollcommand=scroll.set); self.tables_tree.grid(row=0, column=0, sticky="nsew"); scroll.grid(row=0, column=1, sticky="ns")
        actions = tk.Frame(table_card, bg=COLORS["card"]); actions.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 20)); self._button(actions, "Seleccionar todo", self._select_all_tables).pack(side="left"); self._button(actions, "Ejecutar análisis", self._run_analysis, primary=True).pack(side="right")
        self._load_tables_for_database()

    def _load_tables_for_database(self) -> None:
        database = self.database_var.get()
        if not database or self.is_busy: return
        if self.client is None:
            messagebox.showwarning("Conexión no disponible", "No hay una conexión válida para leer metadatos."); return
        self._set_busy(True, "Leyendo metadatos y relaciones de la base de datos…")
        threading.Thread(target=self._metadata_worker, args=(database,), daemon=True).start()

    def _metadata_worker(self, database: str) -> None:
        try:
            tables = self.client.load_metadata(database) if self.client else []; self.after(0, lambda: self._metadata_finished(tables, None))
        except Exception as exc:
            self.after(0, lambda error=str(exc): self._metadata_finished([], error))

    def _metadata_finished(self, tables, error: str | None) -> None:
        self._set_busy(False)
        if error:
            self.status_var.set("No fue posible leer los metadatos"); messagebox.showerror("Error al leer metadatos", error); return
        self._render_tables(tables); self.status_var.set(f"Alcance listo · {len(tables)} tablas encontradas")

    def _render_tables(self, tables) -> None:
        self.loaded_tables = tables
        if not hasattr(self, "tables_tree"): return
        for item in self.tables_tree.get_children(): self.tables_tree.delete(item)
        for index, table in enumerate(self.loaded_tables):
            pk = ", ".join(column.name for column in table.primary_key_columns) or "Sin clave primaria"
            self.tables_tree.insert("", "end", iid=str(index), values=(table.full_name, len(table.columns), pk))
        self._select_all_tables()

    def _select_all_tables(self) -> None:
        if hasattr(self, "tables_tree"): self.tables_tree.selection_set(self.tables_tree.get_children())

    def _run_analysis(self) -> None:
        if self.is_busy: return
        selected = self.tables_tree.selection() if hasattr(self, "tables_tree") else ()
        if not selected:
            messagebox.showwarning("Selección requerida", "Selecciona al menos una tabla para ejecutar el análisis."); return
        self._tables_to_analyze = [self.loaded_tables[int(item)] for item in selected]
        self._set_busy(True, "Perfilando datos y aplicando reglas de 1FN y 2FN…")
        threading.Thread(target=self._analysis_worker,daemon=True).start()

    def _analysis_worker(self) -> None:
        try:
            database=self.database_var.get()
            tables=self.client.profile_tables(database,self._tables_to_analyze)
            result=analyze_database(database,tables)
            self.after(0,lambda:self._analysis_finished(result,tables,None))
        except Exception as exc:
            self.after(0,lambda error=str(exc):self._analysis_finished(None,[],error))

    def _analysis_finished(self,result,tables,error) -> None:
        self._set_busy(False)
        if error:
            messagebox.showerror("Error de análisis",error);return
        self.current_result=result
        self.loaded_tables=tables
        self.history.save(self.server_var.get(),result)
        self.status_var.set(f"Análisis finalizado · {len(result.findings)} hallazgos · muestra hasta 1000 filas/tabla")
        self._show_results()

    def _show_history(self) -> None:
        self._set_active("history");page=self._clear_content()
        self._page_header(page,"Historial de auditorías","Registro local independiente de las bases evaluadas.","PASO 04 · HISTORIAL")
        tree=ttk.Treeview(page,columns=("fecha","base","tablas","hallazgos"),show="headings")
        for name,label in [("fecha","Fecha UTC"),("base","Base evaluada"),("tablas","Tablas"),("hallazgos","Hallazgos")]:
            tree.heading(name,text=label);tree.column(name,width=130 if name in ("tablas","hallazgos") else 280)
        tree.grid(row=1,column=0,sticky="nsew",padx=34,pady=26);page.rowconfigure(1,weight=1)
        for values in self.history.list():tree.insert("","end",values=values)

    def _show_results(self) -> None:
        self._set_active("results"); page = self._clear_content()
        self._page_header(page, "Resultados del diagnóstico", "Hallazgos generados por reglas de Primera y Segunda Forma Normal. Cada resultado debe ser validado por el responsable de la base de datos.", "PASO 03 · RESULTADOS")
        if self.current_result is None: return
        body = tk.Frame(page, bg=COLORS["card"]); body.grid(row=1, column=0, sticky="nsew", padx=34, pady=(24, 32)); body.columnconfigure(0, weight=1); body.rowconfigure(2, weight=1); page.rowconfigure(1, weight=1)
        summary = tk.Frame(body, bg=COLORS["card"]); summary.grid(row=0, column=0, sticky="ew")
        for column in range(4): summary.columnconfigure(column, weight=1)
        status_color = COLORS["success"] if self.current_result.score >= 85 else COLORS["warning"] if self.current_result.score >= 70 else COLORS["danger"]
        for index, (label, value, color) in enumerate((("PUNTUACIÓN", f"{self.current_result.score}/100", COLORS["blue"]), ("ESTADO", self.current_result.status, status_color), ("TABLAS EVALUADAS", str(self.current_result.tables_analyzed), COLORS["text"]), ("HALLAZGOS", str(len(self.current_result.findings)), COLORS["danger"] if self.current_result.findings else COLORS["success"]))):
            metric = tk.Frame(summary, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"]); metric.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 10, 0))
            tk.Label(metric, text=label, bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=15, pady=(14, 2))
            tk.Label(metric, text=value, bg=COLORS["card"], fg=color, font=("Segoe UI Semibold", 16)).pack(anchor="w", padx=15, pady=(0, 14))
        ttk.Progressbar(body, value=self.current_result.score, maximum=100).grid(row=1, column=0, sticky="ew", pady=(16, 16))
        findings_card = tk.Frame(body, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"]); findings_card.grid(row=2, column=0, sticky="nsew"); findings_card.columnconfigure(0, weight=1); findings_card.rowconfigure(1, weight=1)
        tk.Label(findings_card, text="Detalle de hallazgos", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI Semibold", 12)).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 12))
        list_wrap = tk.Frame(findings_card, bg=COLORS["entry"], highlightthickness=1, highlightbackground=COLORS["border"])
        list_wrap.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 8)); list_wrap.columnconfigure(0, weight=1); list_wrap.rowconfigure(1, weight=1)
        list_header = tk.Frame(list_wrap, bg="#19263B"); list_header.grid(row=0, column=0, sticky="ew")
        for column, (label, width) in enumerate((("", 3), ("SEVERIDAD", 12), ("REGLA", 9), ("TABLA", 24), ("HALLAZGO", 70))):
            list_header.columnconfigure(column, weight=1 if column == 4 else 0, minsize=width * 7)
            tk.Label(list_header, text=label, bg="#19263B", fg=COLORS["muted"], font=("Segoe UI Semibold", 8), anchor="w").grid(row=0, column=column, sticky="ew", padx=8, pady=10)
        canvas = tk.Canvas(list_wrap, bg=COLORS["entry"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_wrap, orient="vertical", command=canvas.yview)
        rows = tk.Frame(canvas, bg=COLORS["entry"])
        rows.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=rows, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=1, column=0, sticky="nsew"); scrollbar.grid(row=1, column=1, sticky="ns")
        self.selected_finding = tk.StringVar(value="0" if self.current_result.findings else "")
        self.finding_rows = {}
        if self.current_result.findings:
            for index, finding in enumerate(self.current_result.findings):
                self._finding_row(rows, index, finding)
            self.selected_finding.trace_add("write", lambda *_args: self._refresh_finding_selection())
            self._refresh_finding_selection()
        else:
            tk.Label(rows, text="✓  No se detectaron hallazgos con las reglas evaluadas.", bg=COLORS["entry"], fg=COLORS["success"], font=("Segoe UI Semibold", 10), anchor="w").pack(fill="x", padx=18, pady=24)
        actions = tk.Frame(findings_card, bg=COLORS["card"]); actions.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 20))
        self._button(actions, "Nuevo análisis", self._show_selection).pack(side="left")
        self._button(actions, "Exportar reporte PDF", self._export_report, primary=True).pack(side="right")
        if self.operation_mode.get() == "remediation" and self.current_result.findings:
            remediation_button = self._button(actions, "Preparar remediación", self._open_remediation_modal)
            remediation_button.configure(bg="#4A2D16", fg=COLORS["warning"], activebackground="#5C3719", activeforeground=COLORS["warning"])
            remediation_button.pack(side="right", padx=10)

    def _finding_row(self, parent, index: int, finding) -> None:
        row_bg = COLORS["entry"] if index % 2 == 0 else "#0F1829"
        row = tk.Frame(parent, bg=row_bg, highlightthickness=1, highlightbackground=COLORS["entry"])
        row.pack(fill="x")
        for column, width in enumerate((3, 12, 9, 24, 70)):
            row.columnconfigure(column, weight=1 if column == 4 else 0, minsize=width * 7)
        radio = tk.Radiobutton(row, variable=self.selected_finding, value=str(index), bg=row_bg, activebackground="#182438", selectcolor=COLORS["navy"], cursor="hand2")
        radio.grid(row=0, column=0, padx=8, pady=12)
        severity_bg = "#451A1A" if finding.severity == "Alta" else "#422F12" if finding.severity == "Media" else "#263247"
        severity_fg = "#FCA5A5" if finding.severity == "Alta" else "#FCD34D" if finding.severity == "Media" else COLORS["muted"]
        severity_label = tk.Label(row, text=finding.severity.upper(), bg=severity_bg, fg=severity_fg, font=("Segoe UI Semibold", 8), padx=9, pady=4)
        severity_label.grid(row=0, column=1, sticky="w", padx=8, pady=12)
        rule_label = tk.Label(row, text=finding.rule, bg="#123F48", fg=COLORS["blue"], font=("Segoe UI Semibold", 8), padx=9, pady=4)
        rule_label.grid(row=0, column=2, sticky="w", padx=8, pady=12)
        table_label = tk.Label(row, text=finding.table, bg=row_bg, fg=COLORS["text"], font=("Segoe UI Semibold", 9), anchor="w")
        table_label.grid(row=0, column=3, sticky="ew", padx=8, pady=12)
        message_label = tk.Label(row, text=finding.message+("\n"+finding.evidence if finding.evidence else ""), bg=row_bg, fg=COLORS["muted"], font=("Segoe UI", 9), anchor="w", justify="left", wraplength=500)
        message_label.grid(row=0, column=4, sticky="ew", padx=8, pady=12)
        self.finding_rows[index] = (row, radio, table_label, message_label, row_bg)
        for widget in (row, table_label, message_label, severity_label, rule_label):
            widget.bind("<Button-1>", lambda _event, value=str(index): self.selected_finding.set(value))
        tk.Frame(parent, bg=COLORS["border"], height=1).pack(fill="x")

    def _refresh_finding_selection(self) -> None:
        selected = self.selected_finding.get()
        for index, (row, radio, table_label, message_label, base_bg) in self.finding_rows.items():
            active = str(index) == selected
            background = "#163445" if active else base_bg
            row.configure(bg=background, highlightbackground=COLORS["blue"] if active else COLORS["entry"])
            radio.configure(bg=background, activebackground=background)
            table_label.configure(bg=background, fg=COLORS["white"] if active else COLORS["text"])
            message_label.configure(bg=background, fg="#D8E4F2" if active else COLORS["muted"])

    def _open_remediation_modal(self) -> None:
        if self.operation_mode.get() != "remediation" or self.client is None or self.client.read_only:
            messagebox.showerror("Modo no autorizado", "Vuelva a conectar en modo Remediación Activa para preparar cambios.")
            return
        selected = self.selected_finding.get() if hasattr(self, "selected_finding") else ""
        if not selected:
            messagebox.showwarning("Seleccione un hallazgo", "Seleccione el hallazgo que desea revisar y remediar.")
            return
        index = int(selected)
        finding = self.current_result.findings[index]
        metadata = next((table for table in self.loaded_tables if table.full_name == finding.table), None)
        plan = build_remediation_plan(finding, metadata)
        preflight=None
        preflight_error="Plan informativo: ejecución no habilitada."
        if plan.executable:
            try:
                preflight=self.client.resource_preflight(self.database_var.get(),plan.table)
                preflight_error="Reserva insuficiente: plan bloqueado." if not preflight['allowed'] else ""
            except Exception as exc:
                preflight_error=f"No se pudo verificar capacidad: {type(exc).__name__}."
        modal = tk.Toplevel(self)
        modal.title("Confirmación de alto impacto · NORMADATA")
        modal.geometry("960x880")
        modal.minsize(820, 650)
        modal.configure(bg=COLORS["canvas"])
        modal.transient(self)
        modal.grab_set()
        modal.columnconfigure(0, weight=1)
        modal.rowconfigure(2, weight=1)

        header = tk.Frame(modal, bg="#241A12", highlightthickness=1, highlightbackground="#6B431D")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 14))
        tk.Label(header, text="ALTO IMPACTO", bg="#4A2D16", fg=COLORS["warning"], font=("Segoe UI Semibold", 8), padx=10, pady=5).pack(anchor="w", padx=18, pady=(16, 8))
        tk.Label(header, text=plan.title, bg="#241A12", fg=COLORS["text"], font=("Segoe UI Semibold", 18)).pack(anchor="w", padx=18)
        tk.Label(header, text="Revise el alcance completo antes de autorizar cambios estructurales.", bg="#241A12", fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(5, 16))

        facts = tk.Frame(modal, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"])
        facts.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 14))
        facts.columnconfigure(1, weight=1)
        tk.Label(facts, text="TABLA AFECTADA", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI Semibold", 8)).grid(row=0, column=0, sticky="nw", padx=16, pady=(14, 5))
        tk.Label(facts, text=plan.table, bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI Semibold", 10)).grid(row=0, column=1, sticky="nw", padx=16, pady=(14, 5))
        tk.Label(facts, text="RIESGOS", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI Semibold", 8)).grid(row=1, column=0, sticky="nw", padx=16, pady=5)
        tk.Label(facts, text="\n".join(f"• {risk}" for risk in plan.risks), bg=COLORS["card"], fg=COLORS["warning"], font=("Segoe UI", 9), justify="left", wraplength=650).grid(row=1, column=1, sticky="nw", padx=16, pady=5)
        tk.Label(facts, text="BACKUP", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI Semibold", 8)).grid(row=2, column=0, sticky="nw", padx=16, pady=(5, 14))
        tk.Label(facts, text="Realice y valide un backup completo antes de ejecutar esta remediación.", bg=COLORS["card"], fg=COLORS["danger"], font=("Segoe UI Semibold", 9)).grid(row=2, column=1, sticky="nw", padx=16, pady=(5, 14))
        resource_text=preflight_error or (f"Log libre: {preflight['log_free_bytes']:,} bytes | "
            f"Tabla e índices: {preflight['table_bytes']:,} bytes | "
            f"Requerido (200 %): {preflight['required_bytes']:,} bytes · APTO")
        tk.Label(facts,text="CONTROL DEL LOG",bg=COLORS["card"],fg=COLORS["muted"],font=("Segoe UI Semibold",8)).grid(row=3,column=0,sticky="nw",padx=16,pady=(0,14))
        tk.Label(facts,text=resource_text,bg=COLORS["card"],fg=COLORS["blue"] if not preflight_error else COLORS["danger"],
            font=("Segoe UI",9),wraplength=700,justify="left").grid(row=3,column=1,sticky="nw",padx=16,pady=(0,14))

        preview = tk.Frame(modal, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"])
        preview.grid(row=2, column=0, sticky="nsew", padx=24)
        preview.columnconfigure(0, weight=1); preview.rowconfigure(1, weight=1)
        tk.Label(preview, text="VISTA PREVIA SQL · TRANSACCIÓN PROTEGIDA", bg=COLORS["card"], fg=COLORS["blue"], font=("Segoe UI Semibold", 9)).grid(row=0, column=0, sticky="w", padx=16, pady=12)
        sql_box = tk.Text(preview, bg="#070B13", fg="#C7D2FE", insertbackground=COLORS["blue"], font=("Cascadia Mono", 9), relief="flat", padx=14, pady=12, wrap="none")
        sql_box.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        sql_box.insert("1.0", wrap_transaction(plan.sql,rollback_only=True))
        sql_box.configure(state="disabled")

        footer = tk.Frame(modal, bg=COLORS["canvas"])
        footer.grid(row=3, column=0, sticky="ew", padx=24, pady=18)
        footer.columnconfigure(0, weight=1)
        confirmation = tk.BooleanVar(value=False)
        confirm_text = "Comprendo los riesgos de modificar la estructura y confirmo la ejecución de estos cambios"
        checkbox = tk.Checkbutton(footer, text=confirm_text, variable=confirmation, bg=COLORS["canvas"], fg=COLORS["text"], activebackground=COLORS["canvas"], activeforeground=COLORS["text"], selectcolor=COLORS["navy"], font=("Segoe UI", 9), wraplength=570, justify="left")
        checkbox.grid(row=0, column=0, sticky="w")
        rollback_only = tk.BooleanVar(value=True)
        tk.Checkbutton(footer,text="Ensayo: finalizar con ROLLBACK (sin cambios persistentes)",variable=rollback_only,
            bg=COLORS["canvas"],fg=COLORS["text"],selectcolor=COLORS["navy"],font=("Segoe UI",9)).grid(row=1,column=0,columnspan=2,sticky="w",pady=(8,0))
        execute_button = self._button(footer, "Ejecutar plan", lambda: self._execute_remediation(plan, modal, execute_button,rollback_only=rollback_only.get()), primary=True)
        execute_button.configure(state="disabled", bg="#273449", disabledforeground="#64748B")
        execute_button.grid(row=0, column=1, sticky="e", padx=(14, 0))

        def update_button(*_args) -> None:
            enabled = confirmation.get() and plan.executable and not preflight_error
            execute_button.configure(state="normal" if enabled else "disabled", bg=COLORS["warning"] if enabled else "#273449", fg=COLORS["navy"] if enabled else "#64748B")

        confirmation.trace_add("write", update_button)
        def update_preview(*_args):
            sql_box.configure(state="normal");sql_box.delete("1.0","end")
            sql_box.insert("1.0",wrap_transaction(plan.sql,rollback_only=rollback_only.get()))
            sql_box.configure(state="disabled")
        rollback_only.trace_add("write",update_preview)
        if not plan.executable:
            checkbox.configure(state="disabled")
            tk.Label(footer, text="Este hallazgo requiere diseño manual; el script informativo no puede ejecutarse.", bg=COLORS["canvas"], fg=COLORS["danger"], font=("Segoe UI Semibold", 8), wraplength=720, justify="left").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _execute_remediation(self, plan, modal, button,rollback_only=True) -> None:
        button.configure(state="disabled", text="Ejecutando…")
        self.status_var.set(f"Ejecutando remediación en {plan.table}")
        threading.Thread(target=self._remediation_worker, args=(plan, modal,rollback_only), daemon=True).start()

    def _remediation_worker(self, plan, modal,rollback_only=True) -> None:
        try:
            if self.client is None:
                raise RuntimeError("La conexión SQL Server ya no está disponible.")
            outcome=self.client.execute_plan(self.database_var.get(),plan,rollback_only=rollback_only)
            self.after(0, lambda: self._remediation_finished(modal, None,outcome))
        except Exception as exc:
            self.after(0, lambda error=str(exc): self._remediation_finished(modal, error))

    def _remediation_finished(self, modal, error: str | None,outcome=None) -> None:
        if error:
            self.status_var.set("La remediación fue revertida o no pudo ejecutarse")
            messagebox.showerror("Remediación no aplicada", f"El plan fue rechazado o terminó con error. Verifique el estado registrado.\n\n{error}", parent=modal)
            modal.destroy()
            return
        end=outcome['outcome']
        self.status_var.set(f"Plan finalizado con {end} · vuelva a ejecutar el análisis")
        messagebox.showinfo("Plan completado", f"Resultado transaccional: {end}. Ejecute un nuevo análisis para validar el estado.", parent=modal)
        modal.destroy()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.is_busy = busy
        if busy:
            self.status_var.set(message)
            self.busy_layer = tk.Frame(self.content, bg="#101D30", highlightthickness=1, highlightbackground=COLORS["blue"])
            self.busy_layer.place(relx=.5, rely=.5, anchor="center", width=390, height=165)
            self.busy_canvas = tk.Canvas(self.busy_layer, width=34, height=34, bg="#101D30", highlightthickness=0); self.busy_canvas.pack(pady=(26, 7))
            tk.Label(self.busy_layer, text=message, bg="#101D30", fg=COLORS["text"], font=("Segoe UI Semibold", 10), wraplength=330, justify="center").pack()
            tk.Label(self.busy_layer, text="PROCESAMIENTO EN CURSO", bg="#101D30", fg=COLORS["muted"], font=("Segoe UI Semibold", 8)).pack(pady=(5, 0)); self._animate_spinner()
        elif hasattr(self, "busy_layer"):
            self.busy_layer.destroy(); del self.busy_layer

    def _animate_spinner(self) -> None:
        if not self.is_busy or not hasattr(self, "busy_canvas"): return
        self.busy_canvas.delete("all"); self.busy_canvas.create_arc(4, 4, 30, 30, start=self._spinner_angle, extent=285, style="arc", width=3, outline=COLORS["blue"]); self._spinner_angle = (self._spinner_angle + 18) % 360; self.after(45, self._animate_spinner)

    def _export_report(self) -> None:
        if self.current_result is None: return
        default_name = f"reporte_auditoria_{self.current_result.database}.pdf".replace(" ", "_")
        path = filedialog.asksaveasfilename(title="Guardar reporte de auditoría", defaultextension=".pdf", initialfile=default_name, filetypes=[("Documento PDF", "*.pdf")])
        if not path: return
        try:
            output = export_pdf(self.current_result, Path(path), server=self.server_var.get(), tables=self.loaded_tables); self.status_var.set("Reporte PDF exportado correctamente"); messagebox.showinfo("Reporte generado", f"El reporte se guardó en:\n{output}")
        except Exception as exc:
            messagebox.showerror("No se pudo exportar", str(exc))


def main() -> None:
    app = NormadataApp()
    app.mainloop()
