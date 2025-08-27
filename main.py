# prime_viewer_qt_ultrafast.py
# Version fonctionnelle et optimisée (memmap + UI stable)

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
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QLabel, QPushButton, QTableView, QProgressBar, QFileDialog,
    QGroupBox, QMessageBox, QAbstractItemView, QDialog, QGraphicsDropShadowEffect
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

            self.status_update.emit("Calcul de la borne supérieure...")
            ub = upper_bound_nth_prime(n)

            self.status_update.emit("Crible de base jusqu'à √borne...")
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

            self.status_update.emit("Crible segmenté en cours...")
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
    def __init__(self, mmap_path: Path, count_ref: callable, page_size=10000000, parent=None):
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
        if not index.isValid() or role != Qt.DisplayRole or self._mm is None:
            return None
        row = self.offset + index.row()
        if row >= len(self._mm):
            return None
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


# --- Nouveau Worker pour l'export ---
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

            # bloc de 10M (≈80 Mo de données + formatage) : bon compromis RAM/IO
            block = 10_000_000

            # gros tampon d'écriture pour réduire les syscalls
            with open(self.out_file, "w", encoding="utf-8", buffering=16 * 1024 * 1024, newline="\n") as f:
                written = 0
                while written < total and not self._stop:
                    end = min(written + block, total)
                    arr = mm[written:end]

                    # Ecriture texte « en masse » via tofile (bien plus rapide que savetxt)
                    # + retour à la ligne entre blocs
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
        self.resize(400, 120)

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


# ---------- Interface complète ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Générateur/Visualiseur de Nombres Premiers (Ultra-Fast)")
        self.resize(1000, 700)

        # Activer thème sombre global
        self._apply_dark_theme()

        # état
        self._found = 0
        self._target = 0
        self._pmax = 0
        self._sum = 0
        self._avg = 0.0
        self._thread = None

        # config
        self.cfg = GenConfig(count=10)
        self.mmap_path = self.cfg.tmp_dir / self.cfg.mmap_filename

        # timer
        self._ui_timer = QTimer()
        self._ui_timer.timeout.connect(self._update_ui)

        # construire UI
        self._build_ui()
        self._tune_table()

        # modèle memmap
        self.model = PrimePagedModel(self.mmap_path, self.get_found, page_size=10000000)
        self.table.setModel(self.model)
        self._update_pages()

        # liaisons
        self._connect_signals()

    # ------------------- THEME -------------------
    def _apply_dark_theme(self):
        """Palette sombre inspirée de Material Design"""
        dark_palette = QPalette()

        dark_gray = QColor(30, 30, 30)
        medium_gray = QColor(45, 45, 45)
        light_gray = QColor(200, 200, 200)
        accent = QColor(33, 150, 243)  # bleu Material

        dark_palette.setColor(QPalette.Window, dark_gray)
        dark_palette.setColor(QPalette.Base, medium_gray)
        dark_palette.setColor(QPalette.AlternateBase, dark_gray)
        dark_palette.setColor(QPalette.Text, light_gray)
        dark_palette.setColor(QPalette.Button, medium_gray)
        dark_palette.setColor(QPalette.ButtonText, light_gray)
        dark_palette.setColor(QPalette.Highlight, accent)
        dark_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))

        self.setPalette(dark_palette)

        # QSS global : boutons arrondis + transitions Material
        self.setStyleSheet("""
            QPushButton {
                background-color: #2E2E2E;
                color: #E0E0E0;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #3C3C3C;
            }
            QPushButton:pressed {
                background-color: #1976D2;
            }
            QLineEdit {
                background-color: #383838;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
                color: #E0E0E0;
            }
            QTableView {
                background-color: #212121;
                alternate-background-color: #2A2A2A;
                gridline-color: #444;
                color: #E0E0E0;
                selection-background-color: #1976D2;
                selection-color: white;
            }
            QProgressBar {
                border: none;
                border-radius: 6px;
                text-align: center;
                background-color: #333;
                color: #E0E0E0;
            }
            QProgressBar::chunk {
                background-color: #2196F3;
                border-radius: 6px;
            }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 6px;
                margin-top: 8px;
                padding: 6px;
                font-weight: bold;
                color: #E0E0E0;
            }
        """)

    def _add_shadow(self, widget, blur=18, dx=0, dy=2):
        """Effet ombre portée pour boutons flottants"""
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(blur)
        shadow.setXOffset(dx)
        shadow.setYOffset(dy)
        shadow.setColor(QColor(0, 0, 0, 180))
        widget.setGraphicsEffect(shadow)

    def _update_pages(self):
        total = self.get_found()
        ps = self.model.page_size
        total_pages = (total + ps - 1) // ps if total > 0 else 0
        current_page = (self.model.offset // ps) + 1 if total > 0 else 0
        self.lbl_pages.setText(f"Page {current_page}/{total_pages}")

        # Optionnel : activer/désactiver les boutons
        self.btn_prev.setEnabled(self.model.offset > 0)
        self.btn_next.setEnabled(self.model.offset + ps < total)

    # ------------------- BUILD UI -------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        gb_params = QGroupBox("Paramètres")
        gl = QGridLayout(gb_params)

        gl.addWidget(QLabel("Nombre de nombres premiers :"), 0, 0)
        self.edit_count = QLineEdit("1000000")
        self.edit_count.setMaximumWidth(180)
        gl.addWidget(self.edit_count, 0, 1)

        self.btn_generate = QPushButton("Générer")
        self._add_shadow(self.btn_generate)
        gl.addWidget(self.btn_generate, 0, 2)

        self.btn_stop = QPushButton("Arrêter")
        self.btn_stop.setEnabled(False)
        self._add_shadow(self.btn_stop)
        gl.addWidget(self.btn_stop, 0, 3)

        quick = QHBoxLayout()
        quick.addWidget(QLabel("Sélections rapides :"))
        for v in (10, 100, 1000, 10000, 100000, 1_000_000, 10_000_000, 100_000_000, 1_000_000_000):
            label = "1B" if v == 1_000_000_000 else f"{v:,}".replace(",", " ")
            b = QPushButton(label)
            b.clicked.connect(lambda _, vv=v: self._quick(vv))
            quick.addWidget(b)
        gl.addLayout(quick, 1, 0, 1, 4)

        root.addWidget(gb_params)

        row_prog = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        row_prog.addWidget(self.progress)
        self.lbl_status = QLabel("Prêt.")
        row_prog.addWidget(self.lbl_status)
        root.addLayout(row_prog)

        gb_stats = QGroupBox("Statistiques")
        gs = QGridLayout(gb_stats)
        self.lbl_count = QLabel("0")
        self.lbl_max = QLabel("0")
        self.lbl_avg = QLabel("0")
        self.lbl_sum = QLabel("0")

        gs.addWidget(QLabel("Nombres générés :"), 0, 0)
        gs.addWidget(self.lbl_count, 0, 1)
        gs.addWidget(QLabel("Plus grand nombre :"), 0, 2)
        gs.addWidget(self.lbl_max, 0, 3)

        gs.addWidget(QLabel("Moyenne :"), 1, 0)
        gs.addWidget(self.lbl_avg, 1, 1)
        gs.addWidget(QLabel("Somme totale :"), 1, 2)
        gs.addWidget(self.lbl_sum, 1, 3)

        root.addWidget(gb_stats)

        # Table
        self.table = QTableView()
        root.addWidget(self.table, stretch=1)

        # Navigation
        row_nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Précédent")
        self._add_shadow(self.btn_prev, blur=10)
        self.btn_next = QPushButton("Suivant ▶")
        self._add_shadow(self.btn_next, blur=10)
        self.edit_goto = QLineEdit()
        self.edit_goto.setPlaceholderText("Index")
        self.edit_goto.setMaximumWidth(120)
        self.btn_goto = QPushButton("Aller")
        self._add_shadow(self.btn_goto, blur=10)

        self.lbl_pages = QLabel("Page 0/0")

        row_nav.addWidget(self.btn_prev)
        row_nav.addWidget(self.btn_next)
        row_nav.addWidget(self.edit_goto)
        row_nav.addWidget(self.btn_goto)
        row_nav.addStretch(1)
        row_nav.addWidget(self.lbl_pages)
        root.addLayout(row_nav)

        row_exp = QHBoxLayout()
        self.btn_export = QPushButton("Exporter en .txt")
        self._add_shadow(self.btn_export)
        row_exp.addWidget(self.btn_export)
        row_exp.addStretch(1)
        root.addLayout(row_exp)

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
        tv.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        tv.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        tv.viewport().setAttribute(Qt.WA_StaticContents, True)

    def _connect_signals(self):
        # pagination avec MAJ du label
        self.btn_prev.clicked.connect(self._prev)
        self.btn_next.clicked.connect(self._next)
        self.btn_goto.clicked.connect(self._goto_index)

        # >>> AJOUTS <<<
        self.btn_generate.clicked.connect(self.on_generate)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_export.clicked.connect(self.on_export)

        # quand le modèle bouge, MAJ du label de pages
        self.model.modelReset.connect(self._update_pages)
        self.model.layoutChanged.connect(self._update_pages)

    def _prev(self):
        self.model.prev_page()
        self._update_pages()

    def _next(self):
        self.model.next_page()
        self._update_pages()

    def _goto_index(self):
        try:
            idx = int(self.edit_goto.text())
            self.model.goto_index(idx - 1)  # car index commence à 0
        except Exception:
            pass

    def _update_ui(self):
        # placeholder pour future animation / rafraîchissement léger
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

    def on_progress(self, found: int, total: int):
        old = self._found
        self.set_found(found)
        self._target = total
        if found > old:
            self.model.reload_memmap(self.mmap_path)
        pct = int((found / total) * 100) if total else 0
        self.progress.setValue(pct)
        self.lbl_status.setText(f"Génération... {found:,}/{total:,} ({pct}%)".replace(",", " "))
        self._update_pages()  # <<< AJOUT

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
        self._update_pages()  # <<< AJOUT

    def on_failed(self, msg: str):
        self._ui_timer.stop()
        QMessageBox.critical(self, "Erreur", f"Erreur lors de la génération :\n{msg}")
        self.btn_generate.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._thread = None

    def _quick(self, v: int):
        self.edit_count.setText(str(v))
        self.on_generate()

    def on_generate(self):
        if self._thread is not None:
            return

        unique_name = f"primes_memmap_{os.getpid()}_{int(time.time() * 1000)}.dat"
        self.cfg.mmap_filename = unique_name
        self.mmap_path = self.cfg.tmp_dir / self.cfg.mmap_filename

        # rebind model on new file
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
        self.lbl_status.setText("Initialisation...")
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
            self.lbl_status.setText("Arrêt en cours...")

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

        # Créer popup
        self.export_dialog = ExportDialog(self)

        # Créer thread export
        self.export_thread = ExportThread(self.mmap_path, self._found, txt_file)
        self.export_thread.progress.connect(self.export_dialog.set_progress)
        self.export_thread.finished_ok.connect(self.on_export_finished)
        self.export_thread.failed.connect(self.on_export_failed)

        # Bouton stop
        self.export_dialog.btn_stop.clicked.connect(self.export_thread.stop)

        self.export_thread.start()
        self.export_dialog.show()

    def on_export_finished(self, out_file: str):
        self.export_dialog.close()
        QMessageBox.information(self, "Succès", f"Export terminé :\n- {out_file}")

    def on_export_failed(self, msg: str):
        self.export_dialog.close()
        QMessageBox.critical(self, "Erreur", f"Erreur lors de l'export :\n{msg}")

    def closeEvent(self, event):
        if self._thread is not None:
            self._thread.stop()
            self._thread.wait(1000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
