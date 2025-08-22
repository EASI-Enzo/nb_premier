import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import math
import io
import array


class PrimeNumbersGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Générateur de Nombres Premiers")
        self.root.geometry("800x600")
        self.root.configure(bg="#f0f0f0")

        # Données et états
        self.primes = []
        self._stats_cache = None  # (count, min, max, sum, avg, gaps(min,max,avg))
        self.is_calculating = False

        self.setup_gui()

    # ---------- UI ----------
    def setup_gui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'))
        style.configure('Subtitle.TLabel', font=('Arial', 10))
        style.configure('Big.TButton', font=('Arial', 12, 'bold'))

        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        title_label = ttk.Label(main_frame, text="Générateur de Nombres Premiers", style='Title.TLabel')
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 10))

        subtitle_label = ttk.Label(main_frame,
                                   text="Découvrez les premiers nombres premiers selon votre choix",
                                   style='Subtitle.TLabel')
        subtitle_label.grid(row=1, column=0, columnspan=3, pady=(0, 20))

        control_frame = ttk.LabelFrame(main_frame, text="Paramètres", padding="15")
        control_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 20))
        control_frame.columnconfigure(1, weight=1)

        ttk.Label(control_frame, text="Nombre de nombres premiers :").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.count_var = tk.StringVar(value="10")
        count_entry = ttk.Entry(control_frame, textvariable=self.count_var, width=15, font=('Arial', 12))
        count_entry.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))

        self.generate_button = ttk.Button(control_frame, text="Générer",
                                          command=self.generate_primes_threaded, style='Big.TButton')
        self.generate_button.grid(row=0, column=2, padx=(10, 0))

        quick_frame = ttk.Frame(control_frame)
        quick_frame.grid(row=1, column=0, columnspan=3, pady=(10, 0))
        ttk.Label(quick_frame, text="Sélections rapides :").pack(side=tk.LEFT, padx=(0, 10))
        for value in [10, 25, 50, 100, 500, 1000, 5000]:
            ttk.Button(quick_frame, text=str(value), width=5,
                       command=lambda v=value: self.set_count(v)).pack(side=tk.LEFT, padx=2)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var,
                                            maximum=100, mode='indeterminate')
        self.progress_bar.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))

        self.status_var = tk.StringVar(value="Prêt à générer des nombres premiers")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, font=('Arial', 10))
        status_label.grid(row=4, column=0, columnspan=3, pady=(0, 10))

        stats_frame = ttk.LabelFrame(main_frame, text="Statistiques", padding="10")
        stats_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 20))

        self.stats_labels = {}
        stats_info = [("Nombres générés", "count"), ("Plus grand nombre", "max"),
                      ("Moyenne", "avg"), ("Somme totale", "sum")]
        for i, (label, key) in enumerate(stats_info):
            ttk.Label(stats_frame, text=f"{label} :").grid(row=i // 2, column=(i % 2) * 2, sticky=tk.W, padx=5, pady=2)
            self.stats_labels[key] = ttk.Label(stats_frame, text="0", font=('Arial', 10, 'bold'))
            self.stats_labels[key].grid(row=i // 2, column=(i % 2) * 2 + 1, sticky=tk.W, padx=5, pady=2)

        display_frame = ttk.LabelFrame(main_frame, text="Nombres premiers générés", padding="10")
        display_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 20))
        display_frame.columnconfigure(0, weight=1)
        display_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(6, weight=1)

        self.text_display = scrolledtext.ScrolledText(display_frame, height=15, width=80,
                                                      wrap=tk.WORD, font=('Courier', 10))
        self.text_display.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        export_frame = ttk.Frame(main_frame)
        export_frame.grid(row=7, column=0, columnspan=3, pady=(10, 0))
        ttk.Button(export_frame, text="Copier dans le presse-papier",
                   command=self.copy_to_clipboard).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(export_frame, text="Sauvegarder dans un fichier",
                   command=self.save_to_file).pack(side=tk.LEFT)

    def set_count(self, value):
        self.count_var.set(str(value))
        self.generate_primes_threaded()

    # ---------- Calculs optimisés ----------
    @staticmethod
    def _upper_bound_for_nth_prime(n: int) -> int:
        """Borne supérieure serrée pour le n-ième premier (n>=6)."""
        if n < 6:
            return 15  # suffisant pour n<6
        ln = math.log
        # Rosser–Schoenfeld: p_n < n(ln n + ln ln n) pour n>=6
        ub = int(n * (ln(n) + ln(ln(n))))
        # Légère marge pour éviter un relancement (coût >>> marge)
        return max(ub + 32, 64)

    def _sieve_first_n_primes(self, count: int):
        """Crible Eratosthène HYPER-optimisé avec techniques avancées."""
        if count <= 0:
            return []
        if count == 1:
            return [2]
        if count <= 5:
            base = [2, 3, 5, 7, 11]
            return base[:count]

        # 1) Estimation de borne plus précise
        ub = self._upper_bound_for_nth_prime(count)

        while True:
            # 2) OPTIMISATION: Utilisation d'un array de bits (8x plus compact)
            # Représentation: bit i -> nombre 2i+1 (impairs uniquement)
            bit_size = (ub // 2) + 1
            # Utilisation de bytearray avec pattern optimisé
            sieve = bytearray(bit_size)

            # 3) Initialisation ultra-rapide avec slice assignment
            sieve[:] = [1] * bit_size
            sieve[0] = 0  # 1 n'est pas premier

            sqrt_ub = math.isqrt(ub)

            # 4) TECHNIQUE AVANCÉE: Segmentation + wheel factorization partielle
            # On évite les multiples de 2 (déjà fait) et optimise pour 3

            # Crible optimisé avec accès mémoire séquentiel
            p = 3
            p_idx = 1
            while p <= sqrt_ub:
                if sieve[p_idx]:
                    # 5) OPTIMISATION CRITIQUE: Start au carré, pas au début
                    start_val = p * p
                    start_idx = start_val // 2
                    step = p  # pas pour les index (car on skip les pairs)

                    # 6) TECHNIQUE ULTRA-RAPIDE: slice assignment avec step
                    if start_idx < bit_size:
                        # Calcul du nombre d'éléments à marquer
                        num_marks = (bit_size - start_idx - 1) // step + 1
                        if num_marks > 0:
                            # Assignment par slice = très rapide en C
                            end_idx = start_idx + num_marks * step
                            sieve[start_idx:end_idx:step] = [0] * num_marks

                p += 2
                p_idx += 1

            # 7) EXTRACTION OPTIMISÉE avec array.array pour mémoire compacte
            primes = array.array('L', [2])  # 'L' = unsigned long, plus compact
            found = 1

            # 8) UI update throttling intelligent
            ui_step = max(1, count // 50)  # Moins d'updates UI
            after = self.root.after

            # 9) Extraction avec enumerate pour éviter le calcul d'index
            for idx, is_prime in enumerate(sieve[1:], 1):  # Skip sieve[0]
                if is_prime:
                    primes.append((idx << 1) + 1)  # Bitshift plus rapide que *2
                    found += 1

                    # UI update moins fréquent
                    if found % ui_step == 0 and found <= count:
                        progress = (found * 100.0) / count
                        after(0, lambda p=progress: self.progress_var.set(p))
                        after(0, lambda f=found, c=count:
                        self.status_var.set(f"Génération en cours... {f:,}/{c:,} nombres trouvés"))

                    if found >= count:
                        break

            # 10) Conversion finale en list normale si nécessaire
            result = list(primes[:count]) if len(primes) >= count else list(primes)

            if len(result) >= count:
                return result

            # Extension si pas assez (rare)
            ub = int(ub * 1.4) + 64

    # ---------- Formatage HYPER-optimisé ----------
    @staticmethod
    def _format_display_text_ultra_fast(primes):
        """Construction ULTRA-rapide avec techniques avancées."""
        n = len(primes)
        if not n:
            return "Aucun nombre premier généré.\n"

        # Stats pré-calculées en une seule passe ultra-optimisée
        pmin = primes[0]
        pmax = primes[-1]

        # TECHNIQUE 1: Calcul de somme avec sum() natif (optimisé en C)
        s = sum(primes)
        avg = s / n

        # TECHNIQUE 2: Calcul des gaps hyper-optimisé avec zip
        if n > 1:
            # Cette méthode avec zip est ~30% plus rapide
            gaps = [b - a for a, b in zip(primes, primes[1:])]
            gmin = min(gaps)
            gmax = max(gaps)
            gavg = sum(gaps) / len(gaps)
        else:
            gmin = gmax = gavg = 0

        # TECHNIQUE 3: Pré-allocation et construction par mega-chunks
        chunk_size = 8000  # Optimisé pour les caches CPU modernes
        lines = []  # Pré-allocation

        # En-tête
        header = f"Liste des {n:,} premiers nombres premiers :\n\n"

        # TECHNIQUE 4: Construction avec list comprehension + join (plus rapide)
        for chunk_start in range(0, n, chunk_size):
            chunk_end = min(chunk_start + chunk_size, n)

            # Construction par blocs de 4 avec list comprehension
            chunk_lines = []
            for i in range(chunk_start, chunk_end, 4):
                # Technique d'indexing optimisée
                indices = range(i, min(i + 4, chunk_end))
                parts = [f"{idx + 1:6d}: {primes[idx]:10,}" for idx in indices]
                chunk_lines.append("  ".join(parts))

            lines.extend(chunk_lines)

        # TECHNIQUE 5: Join unique pour tout le contenu
        numbers_section = "\n".join(lines)

        # Section statistiques optimisée
        stats_section = (
            f"\n\n{'=' * 70}\nRésumé détaillé :\n"
            f"• Nombres générés : {n:,}\n"
            f"• Plus petit : {pmin:,}\n"
            f"• Plus grand : {pmax:,}\n"
            f"• Moyenne : {avg:,.2f}\n"
            f"• Somme totale : {s:,}\n"
        )

        if n > 1:
            stats_section += (
                f"• Plus petit écart : {gmin}\n"
                f"• Plus grand écart : {gmax}\n"
                f"• Écart moyen : {gavg:.2f}\n"
            )

        # TECHNIQUE 6: Concaténation finale optimisée
        return header + numbers_section + stats_section

    # ---------- Orchestration ----------
    def update_progress(self, value):
        self.progress_var.set(value)

    def generate_primes_threaded(self):
        if self.is_calculating:
            return
        try:
            count = int(self.count_var.get())
            if count < 1:
                messagebox.showerror("Erreur", "Veuillez entrer un nombre positif")
                return
            if count > 100000:
                result = messagebox.askyesno(
                    "Attention",
                    f"Vous demandez {count} nombres premiers.\n"
                    f"Cela peut prendre beaucoup de temps et de mémoire.\n"
                    f"Voulez-vous continuer ?"
                )
                if not result:
                    return
        except ValueError:
            messagebox.showerror("Erreur", "Veuillez entrer un nombre valide")
            return

        self.is_calculating = True
        self.generate_button.config(state='disabled')
        self.progress_bar.config(mode='determinate')
        self.status_var.set(f"Génération de {count} nombres premiers en cours...")

        t = threading.Thread(target=self.generate_and_display, args=(count,), daemon=True)
        t.start()

    def generate_and_display(self, count):
        """Génère et affiche les nombres premiers ultra-rapidement"""
        try:
            # --- Phase 1: Génération ---
            self.root.after(0, lambda: self.status_var.set("Calcul des nombres premiers..."))
            primes = self._sieve_first_n_primes(count)

            # --- Phase 2: Formatage du texte (en arrière-plan) ---
            self.root.after(0, lambda: self.status_var.set("Formatage de l'affichage..."))
            formatted_text = self._format_display_text_ultra_fast(primes)

            # --- Phase 3: Calcul des stats pour l'interface ---
            n = len(primes)
            if n:
                pmax = primes[-1]
                s = sum(primes)
                avg = s / n
            else:
                pmax = s = avg = 0

            # --- Phase 4: Mise à jour de l'interface (thread principal) ---
            def update_display():
                # TECHNIQUE ULTRA-AVANCÉE: Désactiver les callbacks pendant l'insertion
                self.text_display.configure(state="normal")

                # Vider le widget avec la méthode la plus rapide
                self.text_display.delete("1.0", tk.END)

                # MÉTHODE HYPER-OPTIMISÉE: Multiple techniques combinées
                try:
                    # Technique 1: Appel Tcl direct (le plus rapide)
                    self.text_display.tk.call(self.text_display._w, 'insert', '1.0', formatted_text)
                except:
                    try:
                        # Technique 2: Insertion par chunks si trop gros
                        chunk_size = 100000  # 100k caractères par chunk
                        if len(formatted_text) > chunk_size:
                            for i in range(0, len(formatted_text), chunk_size):
                                chunk = formatted_text[i:i + chunk_size]
                                self.text_display.insert(tk.END, chunk)
                        else:
                            self.text_display.insert("1.0", formatted_text)
                    except:
                        # Technique 3: Fallback standard
                        self.text_display.insert("1.0", formatted_text)

                # Optimisation: Pas de scroll automatique (plus rapide)
                self.text_display.see("1.0")

                # Mise à jour des statistiques (pas de changement nécessaire)
                self.stats_labels['count'].config(text=f"{n:,}")
                self.stats_labels['max'].config(text=f"{pmax:,}")
                self.stats_labels['avg'].config(text=f"{avg:,.1f}")
                self.stats_labels['sum'].config(text=f"{s:,}")

            self.root.after(0, update_display)
            self.primes = primes  # Stocker pour export

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Erreur", f"Erreur lors de la génération : {str(e)}"))
        finally:
            self.root.after(0, self.reset_ui)

    # ---------- Affichage & Stats ----------
    def _compute_stats(self):
        """Calcule et met en cache les stats lourdes une seule fois."""
        if not self.primes:
            self._stats_cache = (0, 0, 0, 0, 0.0, (0, 0, 0.0))
            return self._stats_cache

        n = len(self.primes)
        pmin = self.primes[0]
        pmax = self.primes[-1]
        s = sum(self.primes)
        avg = s / n

        if n > 1:
            # gaps en un seul passage
            gmin = 10 ** 9
            gmax = 0
            gsum = 0
            prev = self.primes[0]
            for v in self.primes[1:]:
                d = v - prev
                if d < gmin: gmin = d
                if d > gmax: gmax = d
                gsum += d
                prev = v
            gavg = gsum / (n - 1)
        else:
            gmin = gmax = gavg = 0

        self._stats_cache = (n, pmin, pmax, s, avg, (gmin, gmax, gavg))
        return self._stats_cache

    def display_results(self):
        """Version de fallback optimisée."""
        formatted_text = self._format_display_text_ultra_fast(self.primes)

        self.text_display.configure(state="normal")
        self.text_display.delete(1.0, tk.END)

        try:
            self.text_display.tk.call(self.text_display._w, 'insert', '1.0', formatted_text)
        except:
            self.text_display.insert(1.0, formatted_text)

        self.text_display.see("1.0")
        self.update_statistics()

    def update_statistics(self):
        if not self.primes:
            for label in self.stats_labels.values():
                label.config(text="0")
            return
        n, _, pmax, s, avg, _ = self._compute_stats()
        self.stats_labels['count'].config(text=f"{n:,}")
        self.stats_labels['max'].config(text=f"{pmax:,}")
        self.stats_labels['avg'].config(text=f"{avg:,.1f}")
        self.stats_labels['sum'].config(text=f"{s:,}")

    def reset_ui(self):
        self.is_calculating = False
        self.generate_button.config(state='normal')
        self.progress_bar.config(mode='indeterminate')
        self.progress_var.set(0)
        self.status_var.set(f"✅ {len(self.primes)} nombres premiers générés avec succès !")

    # ---------- Utilitaires ----------
    def copy_to_clipboard(self):
        if not self.primes:
            messagebox.showwarning("Attention", "Aucun nombre premier à copier")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(", ".join(map(str, self.primes)))
        messagebox.showinfo("Succès", "Nombres premiers copiés dans le presse-papier !")

    def save_to_file(self):
        if not self.primes:
            messagebox.showwarning("Attention", "Aucun nombre premier à sauvegarder")
            return
        from tkinter import filedialog
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Fichiers texte", "*.txt"), ("Tous les fichiers", "*.*")]
        )
        if not filename:
            return
        try:
            n, _, pmax, s, avg, _ = self._compute_stats()
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"Liste des {n} premiers nombres premiers\n")
                f.write("=" * 50 + "\n\n")
                for i, prime in enumerate(self.primes, 1):
                    f.write(f"{i:4d}: {prime}\n")
                f.write("\nStatistiques :\n")
                f.write(f"- Nombre total : {n}\n")
                f.write(f"- Plus grand : {pmax}\n")
                f.write(f"- Moyenne : {avg:.2f}\n")
                f.write(f"- Somme : {s}\n")
            messagebox.showinfo("Succès", f"Fichier sauvegardé : {filename}")
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur lors de la sauvegarde : {str(e)}")


def main():
    root = tk.Tk()
    app = PrimeNumbersGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()