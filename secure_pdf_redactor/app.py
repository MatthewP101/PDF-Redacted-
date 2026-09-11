from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from redaction_engine import RedactionError, ScanResult, redact_pdf, scan_pdf


APP_TITLE = "Secure PDF Redactor"


class RedactorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("900x650")
        self.minsize(760, 520)

        self.scan_result: ScanResult | None = None
        self.password: str | None = None
        self.finding_vars: dict[str, tk.BooleanVar] = {}

        self.input_var = tk.StringVar(value="No PDF selected")
        self.status_var = tk.StringVar(value="Open a PDF to scan for sensitive information.")
        self.dpi_var = tk.StringVar(value="200")

        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text=APP_TITLE, font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            outer,
            text=(
                "Local-only redaction for emails, Australian phone numbers, numeric dates, "
                "MNI numbers, and 6–12 digit identifiers."
            ),
            wraplength=820,
        )
        subtitle.pack(anchor="w", pady=(4, 14))

        file_row = ttk.Frame(outer)
        file_row.pack(fill="x")
        ttk.Button(file_row, text="Open PDF", command=self.open_pdf).pack(side="left")
        ttk.Label(file_row, textvariable=self.input_var).pack(side="left", padx=12, fill="x", expand=True)

        warning = ttk.Label(
            outer,
            text=(
                "Secure mode creates a brand-new flattened PDF after applying true redactions. "
                "The original file is never overwritten. Scanned/image-only pages are blocked "
                "because regex detection cannot safely inspect them without OCR."
            ),
            wraplength=840,
        )
        warning.pack(anchor="w", pady=(12, 10))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Select all", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(controls, text="Clear", command=lambda: self._set_all(False)).pack(side="left", padx=(8, 0))

        ttk.Label(controls, text="Output quality:").pack(side="right", padx=(0, 6))
        dpi_box = ttk.Combobox(
            controls,
            width=8,
            state="readonly",
            values=("150", "200", "300"),
            textvariable=self.dpi_var,
        )
        dpi_box.pack(side="right")
        ttk.Label(controls, text="DPI").pack(side="right", padx=(6, 4))

        results_frame = ttk.LabelFrame(outer, text="Detected values", padding=8)
        results_frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(results_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=self.canvas.yview)
        self.results_inner = ttk.Frame(self.canvas)
        self.results_inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.results_inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.redact_button = ttk.Button(bottom, text="Redact selected →", command=self.export_redacted)
        self.redact_button.pack(side="right")
        self.redact_button.state(["disabled"])

    def _clear_results(self) -> None:
        for child in self.results_inner.winfo_children():
            child.destroy()
        self.finding_vars.clear()

    def _set_all(self, value: bool) -> None:
        for var in self.finding_vars.values():
            var.set(value)

    def _password_prompt(self) -> str | None:
        return simpledialog.askstring(
            APP_TITLE,
            "This PDF is password-protected. Enter the PDF password. It is used only in memory and is not stored:",
            show="*",
            parent=self,
        )

    def open_pdf(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Open PDF",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not path:
            return

        self.password = None
        self.status_var.set("Scanning locally…")
        self.update_idletasks()

        try:
            try:
                result = scan_pdf(path)
            except RedactionError as exc:
                if str(exc) != "PASSWORD_REQUIRED":
                    raise
                password = self._password_prompt()
                if password is None:
                    self.status_var.set("Open cancelled.")
                    return
                self.password = password
                result = scan_pdf(path, password=password)
        except RedactionError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            self.status_var.set("Scan failed.")
            return

        self.scan_result = result
        self.input_var.set(str(result.input_path))
        self._populate_findings(result)

        if result.suspicious_pages:
            pages = ", ".join(map(str, result.suspicious_pages))
            self.status_var.set(
                f"Found {len(result.findings)} unique value(s), but secure export is blocked: "
                f"page(s) {pages} require OCR/manual review."
            )
            self.redact_button.state(["disabled"])
        elif result.blocked_reasons:
            self.status_var.set(
                f"Found {len(result.findings)} unique value(s), but secure export is blocked: "
                + result.blocked_reasons[0]
            )
            self.redact_button.state(["disabled"])
        elif result.findings:
            total = sum(f.count for f in result.findings)
            self.status_var.set(
                f"Found {len(result.findings)} unique value(s) across {total} occurrence(s). Review the list before export."
            )
            self.redact_button.state(["!disabled"])
        else:
            self.status_var.set("No matching sensitive values were detected by the configured rules.")
            self.redact_button.state(["disabled"])

    def _populate_findings(self, result: ScanResult) -> None:
        self._clear_results()

        if not result.findings:
            ttk.Label(self.results_inner, text="No matches.").grid(row=0, column=0, sticky="w", padx=4, pady=4)
            return

        headers = ("Redact", "Type", "Detected value", "Occurrences", "Pages")
        for col, text in enumerate(headers):
            ttk.Label(self.results_inner, text=text, font=("Segoe UI", 10, "bold")).grid(
                row=0, column=col, sticky="w", padx=5, pady=(2, 8)
            )

        for row, finding in enumerate(result.findings, start=1):
            var = tk.BooleanVar(value=True)
            self.finding_vars[finding.key] = var
            ttk.Checkbutton(self.results_inner, variable=var).grid(row=row, column=0, padx=5, pady=3)
            ttk.Label(self.results_inner, text=finding.category).grid(row=row, column=1, sticky="w", padx=5)
            ttk.Label(self.results_inner, text=finding.text).grid(row=row, column=2, sticky="w", padx=5)
            ttk.Label(self.results_inner, text=str(finding.count)).grid(row=row, column=3, sticky="w", padx=5)
            ttk.Label(self.results_inner, text=", ".join(map(str, finding.pages))).grid(
                row=row, column=4, sticky="w", padx=5
            )

        self.results_inner.columnconfigure(2, weight=1)

    def export_redacted(self) -> None:
        if not self.scan_result:
            return

        selected = [key for key, var in self.finding_vars.items() if var.get()]
        if not selected:
            messagebox.showwarning(APP_TITLE, "Select at least one value to redact.", parent=self)
            return

        src = self.scan_result.input_path
        default_name = f"{src.stem}_redacted.pdf"
        output = filedialog.asksaveasfilename(
            parent=self,
            title="Save redacted PDF",
            defaultextension=".pdf",
            initialdir=str(src.parent),
            initialfile=default_name,
            filetypes=[("PDF files", "*.pdf")],
        )
        if not output:
            return

        self.status_var.set("Applying redactions and verifying secure output…")
        self.redact_button.state(["disabled"])
        self.update_idletasks()

        try:
            result = redact_pdf(
                self.scan_result,
                selected,
                output,
                password=self.password,
                dpi=int(self.dpi_var.get()),
            )
        except RedactionError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            self.status_var.set("Export failed; no verified redacted copy was returned.")
            self.redact_button.state(["!disabled"])
            return
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Unexpected error: {exc}", parent=self)
            self.status_var.set("Export failed.")
            self.redact_button.state(["!disabled"])
            return

        self.status_var.set(f"Verified redacted PDF saved: {result.output_path.name}")
        self.redact_button.state(["!disabled"])
        messagebox.showinfo(
            APP_TITLE,
            (
                f"Redacted {result.redacted_values} selected value(s) across "
                f"{result.redacted_occurrences} occurrence(s).\n\n"
                f"Saved to:\n{result.output_path}\n\n"
                f"SHA-256:\n{result.sha256}\n\n"
                "The output was rebuilt as a flattened PDF and reopened for verification."
            ),
            parent=self,
        )


if __name__ == "__main__":
    app = RedactorApp()
    app.mainloop()
