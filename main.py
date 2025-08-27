# Version fonctionnelle + design retravaillé (dark, cartes, micro-animations)
# Compatible PyInstaller (aucune ressource externe, pas d’images, pas d’emojis)

import sys
import os
import math
import time
import tempfile
import gc
import shutil
from pathlib import Path
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
    QThread,
    Signal,
    QTimer,
    QEasingCurve,
    QPropertyAnimation,
)
from PySide6.QtGui import QColor, QPalette, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLineEdit,
    QLabel,
    QPushButton,
    QTableView,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QAbstractItemView,
    QDialog,
    QGraphicsDropShadowEffect,
    QFrame,
    QHeaderView,
    QStyle,
    QStyleOption,
)


# ---------- Bornes supérieures (resserrées) ----------
def upper_bound_nth_prime(n: int) -> int:
    if n < 6:
        return 15
    ln_n = math.log(n)
    lnln = math.log(ln_n)
    bound = n * (ln_n + lnln - 1 + (lnln - 2.0) / ln_n)
    if n >= 1_000_000:
        bound *= 1.08
    elif n >= 100_000:
        bound *= 1.06
    else:
        bound *= 1.04
    return int(bound) + 1024


# ---------- Config ----------
@dataclass
class GenConfig:
    count: int
    segment_size: int = 1 << 22
    tmp_dir: Path = Path(tempfile.gettempdir())
    mmap_filename: str = "primes_memmap.dat"
    update_interval_ms: int = 75


# ---------- Utilitaires UI ----------
class Card(QFrame):
    """Carte stylée (conteneur visuel)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setAttribute(Qt.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)


def set_monospace(widget: QWidget):
    # Police monospacée portable
    font = QFont("Consolas")
    if not QFont("Consolas").exactMatch():
        font = QFont("Menlo")
    if not font.exactMatch():
        font = QFont("Courier New")
    font.setStyleHint(QFont.Monospace)
    widget.setFont(font)


# ---------- Worker thread ----------
class PrimeGenThread(QThread):
    progress = Signal(int, int)                # found, total
    finished_ok = Signal(object, object, object, float)  # n_found, pmax, sum, avg
    failed = Signal(str)
    status_update = Signal(str)

    def __init__(self, cfg: GenConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._stop = False
        self._found = 0
        self._target = cfg.count
        self._last_update_ms = 0

    def stop(self):
        self._stop = True

    @staticmethod
    def _safe_remove(path: Path, retries: int = 3):
        for _ in range(retries):
            try:
                if path.exists():
                    path.unlink()
                return True
            except Exception:
                time.sleep(0.05)
        return not path.exists()

    def _emit_progress_if_needed(self):
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_update_ms >= self.cfg.update_interval_ms:
            self.progress.emit(self._found, self._target)
            self._last_update_ms = now_ms

    def _ensure_disk_space(self, n: int, target_dir: Path):
        required = 8 * n + (16 << 20)
        try:
            usage = shutil.disk_usage(str(target_dir))
            if usage.free < required:
                return False, required, usage.free
        except Exception:
            return True, required, None
        return True, required, usage.free

    def run(self):
        try:
            n = int(self.cfg.count)
            if n <= 0:
                self.failed.emit("Le nombre demandé doit être > 0.")
                return

            ok_space, need_bytes, free_bytes = self._ensure_disk_space(n, self.cfg.tmp_dir)
            if not ok_space:
                need_gb = need_bytes / (1 << 30)
                free_gb = (free_bytes or 0) / (1 << 30)
                self.failed.emit(
                    f"Espace disque insuffisant dans {self.cfg.tmp_dir}.\n"
                    f"Requis ≈ {need_gb:.2f} Gio, libre ≈ {free_gb:.2f} Gio."
                )
                return

            self.status_update.emit("Calcul de la borne supérieure…")
            ub = upper_bound_nth_prime(n)

            self.status_update.emit("Crible de base jusqu'à √borne…")
            base_limit = int(math.isqrt(ub)) + 1
            base_sieve_size = (base_limit + 1) // 2
            base_sieve = np.ones(base_sieve_size, dtype=np.bool_)
            sqrt_bl = int(math.isqrt(base_limit)) + 1
            for i in range(1, (sqrt_bl + 1) // 2):
                if base_sieve[i]:
                    p = 2 * i + 1
                    start = (p * p) // 2
                    base_sieve[start::p] = False

            base_indices = np.nonzero(base_sieve)[0][1:]
            base_primes = base_indices * 2 + 1
            odd_primes = base_primes.astype(np.int64, copy=False)

            mmap_path = self.cfg.tmp_dir / self.cfg.mmap_filename
            if mmap_path.exists():
                if not self._safe_remove(mmap_path):
                    self.failed.emit(f"Impossible de supprimer : {mmap_path}")
                    return

            mm = np.memmap(mmap_path, dtype=np.uint64, mode='w+', shape=(n,))
            self._found = 0
            total_sum = np.uint64(0)
            pmax = 0

            # add 2
            mm[0] = 2
            self._found = 1
            total_sum = np.uint64(2)
            pmax = 2
            self._emit_progress_if_needed()

            if self._stop:
                mm.flush(); del mm; gc.collect()
                self.finished_ok.emit(self._found, pmax, int(total_sum), float(int(total_sum) / max(1, self._found)))
                return
            if self._found >= n:
                mm.flush(); del mm; gc.collect()
                self.finished_ok.emit(self._found, pmax, int(total_sum), float(int(total_sum)))
                return

            self.status_update.emit("Crible segmenté en cours…")
            seg_impairs = int(self.cfg.segment_size)
            current = 3
            next_mults = None

            while self._found < n and not self._stop:
                seg_end = min(current + 2 * seg_impairs, ub + 1)
                if current >= seg_end:
                    ub = int(ub * 1.2) + 1024
                    seg_end = current + 2 * seg_impairs

                seg_len = (seg_end - current + 1) // 2
                if seg_len <= 0:
                    break

                segment = np.ones(seg_len, dtype=np.bool_)

                sqrt_seg = int(math.isqrt(seg_end - 1))
                limit_idx = int(np.searchsorted(odd_primes, sqrt_seg, side='right'))

                if limit_idx > 0:
                    if next_mults is None or len(next_mults) != len(odd_primes):
                        next_mults = np.empty(len(odd_primes), dtype=np.int64)
                        c = current
                        for i, p in enumerate(odd_primes):
                            s = p * p
                            if s < c:
                                r = c % p
                                s = (c if r == 0 else c + (p - r))
                            if (s & 1) == 0:
                                s += p
                            next_mults[i] = s

                    c = current
                    se = seg_end
                    for i in range(limit_idx):
                        p = int(odd_primes[i])
                        s = int(next_mults[i])
                        if s >= se:
                            continue
                        idx = (s - c) >> 1
                        segment[idx::p] = False
                        step = p << 1
                        delta = se - s
                        k = (delta + step - 1) // step
                        next_mults[i] = s + k * step

                prime_idx = np.flatnonzero(segment)
                if prime_idx.size:
                    primes = (current + (prime_idx.astype(np.int64) << 1)).astype(np.uint64, copy=False)
                    can_take = n - self._found
                    if primes.size > can_take:
                        primes = primes[:can_take]
                    start = self._found
                    end = start + primes.size
                    if primes.size:
                        mm[start:end] = primes
                        self._found = end
                        block_sum = np.add.reduce(primes, dtype=np.uint64)
                        total_sum = (total_sum + block_sum).astype(np.uint64, copy=False)
                        pmax = int(primes[-1])
                        self._emit_progress_if_needed()
                        if self._found >= n or self._stop:
                            break

                current = seg_end
                if current >= ub and self._found < n:
                    ub = int(ub * 1.2) + 1024

            avg = float(int(total_sum) / max(1, self._found))
            mm.flush()
            del mm
            gc.collect()
            self.finished_ok.emit(self._found, pmax, int(total_sum), avg)

        except Exception as e:
            try:
                if 'mm' in locals():
                    del mm
                gc.collect()
            except Exception:
                pass
            self.failed.emit(str(e))


# ---------- Modèle Qt ----------
class PrimePagedModel(QAbstractTableModel):
    def __init__(self, mmap_path: Path, count_ref: callable, page_size=10_000_000, parent=None):
        super().__init__(parent)
        self.mmap_path = Path(mmap_path) if mmap_path is not None else None
        self.count_ref = count_ref
        self._mm = None
        self.page_size = page_size
        self.offset = 0
        self._open_memmap()

    def _open_memmap(self):
        if self.mmap_path and self.mmap_path.exists():
            self._mm = np.memmap(self.mmap_path, dtype=np.uint64, mode='r')
        else:
            self._mm = None

    def rowCount(self, parent=QModelIndex()):
        total = self.count_ref() or 0
        if total == 0:
            return 0
        return min(self.page_size, total - self.offset)

    def columnCount(self, parent=QModelIndex()):
        return 2

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._mm is None:
            return None
        row = self.offset + index.row()
        if row >= (len(self._mm) if self._mm is not None else 0):
            return None
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return row + 1
            elif index.column() == 1:
                return int(self._mm[row])
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return ["Index", "Nombre premier"][section]
        return str(section + 1)

    def next_page(self):
        total = self.count_ref() or 0
        if self.offset + self.page_size < total:
            self.offset += self.page_size
            self.layoutChanged.emit()

    def prev_page(self):
        if self.offset - self.page_size >= 0:
            self.offset -= self.page_size
            self.layoutChanged.emit()

    def goto_index(self, idx: int):
        total = self.count_ref() or 0
        if 0 <= idx < total:
            self.offset = (idx // self.page_size) * self.page_size
            self.layoutChanged.emit()

    def reload_memmap(self, mmap_path: Path):
        self.mmap_path = Path(mmap_path)
        self._mm = None
        self.offset = 0
        self._open_memmap()
        self.beginResetModel()
        self.endResetModel()


# --- Worker d'export ---
class ExportThread(QThread):
    progress = Signal(int, int)   # écrit, total
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, mmap_path: Path, count: int, out_file: str, parent=None):
        super().__init__(parent)
        self.mmap_path = mmap_path
        self.count = count
        self.out_file = out_file
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            mm = np.memmap(self.mmap_path, dtype=np.uint64, mode="r")
            total = min(self.count, len(mm))
            block = 10_000_000
            with open(self.out_file, "w", encoding="utf-8", buffering=16 * 1024 * 1024, newline="\n") as f:
                written = 0
                while written < total and not self._stop:
                    end = min(written + block, total)
                    arr = mm[written:end]
                    arr.tofile(f, sep="\n", format="%d")
                    if end < total:
                        f.write("\n")
                    written = end
                    self.progress.emit(written, total)
            del mm
            if self._stop:
                self.failed.emit("Export interrompu par l'utilisateur.")
            else:
                self.finished_ok.emit(self.out_file)
        except Exception as e:
            self.failed.emit(str(e))


class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export en cours…")
        self.setModal(True)
        self.resize(420, 130)
        layout = QVBoxLayout(self)
        self.lbl_status = QLabel("Préparation de l'export…")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.btn_stop = QPushButton("Arrêter")
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.progress)
        layout.addWidget(self.btn_stop)

    def set_progress(self, done, total):
        pct = int((done / total) * 100) if total else 0
        self.progress.setValue(pct)
        self.lbl_status.setText(f"Export… {done:,}/{total:,} ({pct}%)".replace(",", " "))


# ---------- Fenêtre principale ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prime Viewer – Ultra-Fast")
        self.resize(1120, 720)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)

        # DPI-aware sizing
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        # État
        self._found = 0
        self._target = 0
        self._pmax = 0
        self._sum = 0
        self._avg = 0.0
        self._thread = None

        # Config
        self.cfg = GenConfig(count=10)
        self.mmap_path = self.cfg.tmp_dir / self.cfg.mmap_filename

        # Timer UI
        self._ui_timer = QTimer()
        self._ui_timer.timeout.connect(self._pulse_progress)

        # Thème + QSS
        self._apply_dark_theme()

        # Construire UI
        self._build_ui()
        self._tune_table()

        # Modèle memmap
        self.model = PrimePagedModel(self.mmap_path, self.get_found, page_size=10_000_000)
        self.table.setModel(self.model)
        self._update_pages()

        # Liaisons
        self._connect_signals()

        # Entrée par défaut
        self.edit_count.setFocus()

        # Apparition en fondu
        self._fade_in()

    # ------------------- THEME -------------------
    def _apply_dark_theme(self):
        base_bg = QColor(18, 18, 20)
        card_bg = QColor(30, 30, 34)
        text = QColor(230, 230, 235)
        accent = QColor(65, 160, 255)

        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, base_bg)
        pal.setColor(QPalette.ColorRole.Base, QColor(28, 28, 32))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(24, 24, 28))
        pal.setColor(QPalette.ColorRole.Text, text)
        pal.setColor(QPalette.ColorRole.Button, card_bg)
        pal.setColor(QPalette.ColorRole.ButtonText, text)
        pal.setColor(QPalette.ColorRole.Highlight, accent)
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        pal.setColor(QPalette.ColorRole.ToolTipBase, card_bg)
        pal.setColor(QPalette.ColorRole.ToolTipText, text)
        self.setPalette(pal)

        self.setFont(QFont("Segoe UI", 10))

        # QSS global + patch pour popups
        self.setStyleSheet(
            """
            QWidget { color: #E6E6EB; }
            QToolTip { background: #1E1E22; border: 1px solid #2E2E36; border-radius: 6px; padding: 6px 8px; }

            /* Patch popups */
            QDialog, QMessageBox, QFileDialog {
                background-color: #1E1E20;
                color: #E6E6EB;
            }

            QPushButton {
                background-color: #2A2A30;
                color: #E6E6EB;
                border: 1px solid #33333A;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #32323A; }
            QPushButton:pressed { background-color: #1976D2; }
            QPushButton:disabled { color: #808089; border-color: #2A2A30; background: #1E1E24; }

            QLineEdit {
                background-color: #232329;
                border: 1px solid #3A3A44;
                border-radius: 10px;
                padding: 8px 10px;
                selection-background-color: #1976D2;
            }

            QProgressBar {
                border: 1px solid #2E2E36;
                border-radius: 10px;
                text-align: center;
                background-color: #1F1F23;
                padding: 2px;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background-color: #2196F3;
                margin: 2px;
            }

            QFrame#Card {
                background-color: #1F1F24;
                border: 1px solid #2A2A31;
                border-radius: 16px;
            }

            QTableView {
                background-color: #17171A;
                alternate-background-color: #1F1F23;
                gridline-color: #2C2C33;
                color: #E6E6EB;
                selection-background-color: #1976D2;
                selection-color: white;
                border: 1px solid #2A2A31;
                border-radius: 12px;
            }
            QHeaderView::section {
                background-color: #24242A;
                color: #CFCFD7;
                padding: 8px;
                border: none;
                border-right: 1px solid #2E2E36;
                font-weight: 700;
                text-transform: uppercase;
            }
            QHeaderView::section:horizontal { border-top-left-radius: 12px; border-top-right-radius: 12px; }

            QScrollBar:vertical {
                width: 12px; background: #1A1A1E; margin: 14px 0 14px 0; border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                min-height: 30px; background: #2C2C34; border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover { background: #3A3A44; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 14px; background: transparent; }

            QLabel.subtle { color: #A0A0AA; }
            QLabel.kpi { font-size: 18px; font-weight: 800; }
            QLabel.kpiTitle { color: #A0A0AA; }
            """
        )

    # ------------------- BUILD UI -------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # Header
        header = Card()
        top = QHBoxLayout(header)
        top.setContentsMargins(16, 16, 16, 16)
        title = QLabel("Générateur / Visualiseur de nombres premiers")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel("Memmap ultra-rapide, pagination massive, export optimisé")
        subtitle.setObjectName("subtitle")
        subtitle.setProperty("class", "subtle")
        subtitle.setStyleSheet("color:#A0A0AA;")
        top.addWidget(self._stacked(title, subtitle))
        top.addStretch(1)
        root.addWidget(header)

        # Paramètres + Statistiques
        row = QHBoxLayout()
        row.setSpacing(12)

        # Carte paramètres
        card_params = Card()
        params = QGridLayout(card_params)
        params.setContentsMargins(16, 16, 16, 16)
        params.setHorizontalSpacing(10)
        params.setVerticalSpacing(10)

        lbln = QLabel("Nombre de nombres premiers :")
        self.edit_count = QLineEdit("1000000")
        self.edit_count.setMaximumWidth(200)
        self.edit_count.setClearButtonEnabled(True)
        self.btn_generate = QPushButton("Générer")
        self.btn_stop = QPushButton("Arrêter")
        self.btn_stop.setEnabled(False)

        quick = QHBoxLayout()
        quick.setSpacing(8)
        quick.addWidget(QLabel("Sélections rapides :"))
        for v in (10, 100, 1000, 10000, 100000, 1_000_000, 10_000_000, 100_000_000, 1_000_000_000):
            label = "1B" if v == 1_000_000_000 else f"{v:,}".replace(",", " ")
            b = QPushButton(label)
            b.setToolTip(f"Générer {label} nombres")
            b.clicked.connect(lambda _, vv=v: self._quick(vv))
            quick.addWidget(b)
        quick.addStretch(1)

        params.addWidget(lbln, 0, 0)
        params.addWidget(self.edit_count, 0, 1)
        params.addWidget(self.btn_generate, 0, 2)
        params.addWidget(self.btn_stop, 0, 3)
        params.addLayout(quick, 1, 0, 1, 4)

        # Carte stats
        card_stats = Card()
        stats = QGridLayout(card_stats)
        stats.setContentsMargins(16, 16, 16, 16)
        stats.setHorizontalSpacing(18)
        stats.setVerticalSpacing(10)

        self.lbl_count = QLabel("0")
        self.lbl_max = QLabel("0")
        self.lbl_avg = QLabel("0")
        self.lbl_sum = QLabel("0")
        for w in (self.lbl_count, self.lbl_max, self.lbl_avg, self.lbl_sum):
            w.setProperty("class", "kpi")
            w.setStyleSheet("font-size:22px;font-weight:900;")
        stats.addWidget(QLabel("Nombres générés"), 0, 0)
        stats.addWidget(self.lbl_count, 1, 0)
        stats.addWidget(QLabel("Plus grand nombre"), 0, 1)
        stats.addWidget(self.lbl_max, 1, 1)
        stats.addWidget(QLabel("Moyenne"), 0, 2)
        stats.addWidget(self.lbl_avg, 1, 2)
        stats.addWidget(QLabel("Somme totale"), 0, 3)
        stats.addWidget(self.lbl_sum, 1, 3)

        row.addWidget(card_params, 2)
        row.addWidget(card_stats, 3)
        root.addLayout(row)

        # Progress + statut
        card_prog = Card()
        pr = QHBoxLayout(card_prog)
        pr.setContentsMargins(16, 16, 16, 16)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.lbl_status = QLabel("Prêt.")
        self.lbl_status.setProperty("class", "subtle")
        pr.addWidget(self.progress, 4)
        pr.addSpacing(12)
        pr.addWidget(self.lbl_status, 1)
        root.addWidget(card_prog)

        # Table
        card_table = Card()
        tvlay = QVBoxLayout(card_table)
        tvlay.setContentsMargins(12, 12, 12, 12)
        self.table = QTableView()
        set_monospace(self.table)
        tvlay.addWidget(self.table)
        root.addWidget(card_table, stretch=1)

        # Navigation + export
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.btn_prev = QPushButton("< Précédent")
        self.btn_next = QPushButton("Suivant >")
        self.edit_goto = QLineEdit()
        self.edit_goto.setPlaceholderText("Index")
        self.edit_goto.setMaximumWidth(140)
        self.btn_goto = QPushButton("Aller")
        self.lbl_pages = QLabel("Page 0/0")
        self.lbl_pages.setProperty("class", "subtle")
        self.btn_export = QPushButton("Exporter en .txt")
        bottom.addWidget(self.btn_prev)
        bottom.addWidget(self.btn_next)
        bottom.addWidget(self.edit_goto)
        bottom.addWidget(self.btn_goto)
        bottom.addStretch(1)
        bottom.addWidget(self.lbl_pages)
        bottom.addSpacing(16)
        bottom.addWidget(self.btn_export)
        root.addLayout(bottom)

    def _stacked(self, title: QLabel, subtitle: QLabel) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(title)
        lay.addWidget(subtitle)
        return w

    def _tune_table(self):
        tv = self.table
        tv.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        tv.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        tv.setAlternatingRowColors(True)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tv.setShowGrid(False)
        tv.setWordWrap(False)
        tv.setTextElideMode(Qt.ElideRight)
        tv.verticalHeader().setVisible(False)
        tv.horizontalHeader().setStretchLastSection(True)
        tv.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tv.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        tv.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        tv.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        tv.viewport().setAttribute(Qt.WA_StaticContents, True)
        # Taille de ligne confortable
        tv.verticalHeader().setDefaultSectionSize(tv.fontMetrics().height() + 10)

    def _connect_signals(self):
        # pagination
        self.btn_prev.clicked.connect(self._prev)
        self.btn_next.clicked.connect(self._next)
        self.btn_goto.clicked.connect(self._goto_index)
        self.edit_goto.returnPressed.connect(self._goto_index)

        # génération
        self.btn_generate.clicked.connect(self.on_generate)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_export.clicked.connect(self.on_export)

    # ------------------- Animations -------------------
    def _fade_in(self):
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(280)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.InOutCubic)
        self._fade.start()

    def _pulse_progress(self):
        # Micro-impulsions visuelles: rien d’intrusif, juste une mise à jour régulière
        val = self.progress.value()
        self.progress.setValue(val)

    # ------------------- Données & état -------------------
    def _update_pages(self):
        total = self.get_found()
        ps = self.model.page_size
        total_pages = (total + ps - 1) // ps if total > 0 else 0
        current_page = (self.model.offset // ps) + 1 if total > 0 else 0
        self.lbl_pages.setText(f"Page {current_page}/{total_pages}")
        self.btn_prev.setEnabled(self.model.offset > 0)
        self.btn_next.setEnabled(self.model.offset + ps < total)

    def _prev(self):
        self.model.prev_page()
        self._update_pages()

    def _next(self):
        self.model.next_page()
        self._update_pages()

    def _goto_index(self):
        try:
            idx = int(self.edit_goto.text())
            self.model.goto_index(idx - 1)
        except Exception:
            pass

    def get_found(self) -> int:
        return self._found

    def set_found(self, v: int):
        self._found = int(v)
        self.lbl_count.setText(f"{self._found:,}".replace(",", " "))

    def set_stats(self, pmax: int, s: int, avg: float):
        self._pmax = int(pmax)
        self._sum = int(s)
        self._avg = float(avg)
        self.lbl_max.setText(f"{self._pmax:,}".replace(",", " "))
        self.lbl_sum.setText(f"{self._sum:,}".replace(",", " "))
        self.lbl_avg.setText(f"{self._avg:,.2f}".replace(",", " "))

    # ------------------- Callbacks worker -------------------
    def on_progress(self, found: int, total: int):
        old = self._found
        self.set_found(found)
        self._target = total
        if found > old:
            self.model.reload_memmap(self.mmap_path)
        pct = int((found / total) * 100) if total else 0
        self.progress.setValue(pct)
        self.lbl_status.setText(f"Génération… {found:,}/{total:,} ({pct}%)".replace(",", " "))
        self._update_pages()

    def on_status_update(self, msg: str):
        self.lbl_status.setText(msg)

    def on_finished_ok(self, n, pmax, s, avg):
        self._ui_timer.stop()
        old = self._found
        self.set_found(int(n))
        if self._found > old:
            try:
                self.model.reload_memmap(self.mmap_path)
            except Exception:
                pass
        self.set_stats(int(pmax), int(s), float(avg))
        self.progress.setValue(100)
        self.lbl_status.setText("Terminé.")
        self.btn_generate.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._thread = None
        self._update_pages()

    def on_failed(self, msg: str):
        self._ui_timer.stop()
        QMessageBox.critical(self, "Erreur", f"Erreur lors de la génération :\n{msg}")
        self.btn_generate.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._thread = None

    # ------------------- Génération / Export -------------------
    def _quick(self, v: int):
        self.edit_count.setText(str(v))
        self.on_generate()

    def on_generate(self):
        if self._thread is not None:
            return

        # Fichier memmap unique par session
        unique_name = f"primes_memmap_{os.getpid()}_{int(time.time() * 1000)}.dat"
        self.cfg.mmap_filename = unique_name
        self.mmap_path = self.cfg.tmp_dir / self.cfg.mmap_filename
        self.model.reload_memmap(self.mmap_path)

        try:
            total = int(self.edit_count.text().replace(" ", ""))
            if total < 1:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Entrée invalide", "Veuillez entrer un entier positif.")
            return

        self._target = total
        self.set_found(0)
        self.set_stats(0, 0, 0.0)
        self.progress.setValue(0)
        self.lbl_status.setText("Initialisation…")
        self.btn_generate.setEnabled(False)
        self.btn_stop.setEnabled(True)

        if total >= 1_000_000_000:
            segment_size = 1 << 23
            update_interval = 125
        elif total >= 100_000_000:
            segment_size = 1 << 22
            update_interval = 90
        elif total >= 10_000_000:
            segment_size = 1 << 21
            update_interval = 60
        else:
            segment_size = 1 << 20
            update_interval = 40

        cfg = GenConfig(
            count=total,
            segment_size=segment_size,
            update_interval_ms=update_interval,
            tmp_dir=self.cfg.tmp_dir,
            mmap_filename=self.cfg.mmap_filename
        )

        self._thread = PrimeGenThread(cfg)
        self._thread.progress.connect(self.on_progress)
        self._thread.finished_ok.connect(self.on_finished_ok)
        self._thread.failed.connect(self.on_failed)
        self._thread.status_update.connect(self.on_status_update)
        self._thread.start()

        self._ui_timer.start(33)

    def on_stop(self):
        if self._thread is not None:
            self._thread.stop()
            self.btn_stop.setEnabled(False)
            self.lbl_status.setText("Arrêt en cours…")

    def on_export(self):
        if self._found <= 0 or not self.mmap_path.exists():
            QMessageBox.information(self, "Information", "Aucune donnée à exporter.")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter en .txt",
            "primes",
            "Fichiers texte (*.txt);;Tous les fichiers (*)"
        )
        if not filename:
            return
        txt_file = filename if filename.endswith(".txt") else filename + ".txt"

        self.export_dialog = ExportDialog(self)
        self.export_thread = ExportThread(self.mmap_path, self._found, txt_file)
        self.export_thread.progress.connect(self.export_dialog.set_progress)
        self.export_thread.finished_ok.connect(self.on_export_finished)
        self.export_thread.failed.connect(self.on_export_failed)
        self.export_dialog.btn_stop.clicked.connect(self.export_thread.stop)
        self.export_thread.start()
        self.export_dialog.show()

    def on_export_finished(self, out_file: str):
        self.export_dialog.close()
        QMessageBox.information(self, "Succès", f"Export terminé :\n- {out_file}")

    def on_export_failed(self, msg: str):
        self.export_dialog.close()
        QMessageBox.critical(self, "Erreur", f"Erreur lors de l'export :\n{msg}")

    # ------------------- Cycle de vie -------------------
    def closeEvent(self, event):
        if self._thread is not None:
            self._thread.stop()
            self._thread.wait(1000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("Prime Viewer – Ultra-Fast")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
