import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import math


class PrimeNumbersGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Générateur de Nombres Premiers")
        self.root.geometry("800x600")
        self.root.configure(bg="#f0f0f0")

        # Variables
        self.primes = []
        self.is_calculating = False

        self.setup_gui()

    def setup_gui(self):
        # Style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'))
        style.configure('Subtitle.TLabel', font=('Arial', 10))
        style.configure('Big.TButton', font=('Arial', 12, 'bold'))

        # Frame principal
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configuration du grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        # Titre
        title_label = ttk.Label(main_frame,
                                text="Générateur de Nombres Premiers",
                                style='Title.TLabel')
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 10))

        subtitle_label = ttk.Label(main_frame,
                                   text="Découvrez les premiers nombres premiers selon votre choix",
                                   style='Subtitle.TLabel')
        subtitle_label.grid(row=1, column=0, columnspan=3, pady=(0, 20))

        # Frame de contrôle
        control_frame = ttk.LabelFrame(main_frame, text="Paramètres", padding="15")
        control_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 20))
        control_frame.columnconfigure(1, weight=1)

        # Saisie du nombre
        ttk.Label(control_frame, text="Nombre de nombres premiers :").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))

        self.count_var = tk.StringVar(value="10")
        count_entry = ttk.Entry(control_frame,
                                textvariable=self.count_var,
                                width=15, font=('Arial', 12))
        count_entry.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))

        # Bouton génération
        self.generate_button = ttk.Button(control_frame,
                                          text="Générer",
                                          command=self.generate_primes_threaded,
                                          style='Big.TButton')
        self.generate_button.grid(row=0, column=2, padx=(10, 0))

        # Boutons rapides
        quick_frame = ttk.Frame(control_frame)
        quick_frame.grid(row=1, column=0, columnspan=3, pady=(10, 0))

        ttk.Label(quick_frame, text="Sélections rapides :").pack(side=tk.LEFT, padx=(0, 10))

        quick_values = [10, 25, 50, 100, 500, 1000, 5000]
        for value in quick_values:
            btn = ttk.Button(quick_frame,
                             text=str(value),
                             width=5,
                             command=lambda v=value: self.set_count(v))
            btn.pack(side=tk.LEFT, padx=2)

        # Barre de progression
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame,
                                            variable=self.progress_var,
                                            maximum=100,
                                            mode='indeterminate')
        self.progress_bar.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))

        # Label de statut
        self.status_var = tk.StringVar(value="Prêt à générer des nombres premiers")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, font=('Arial', 10))
        status_label.grid(row=4, column=0, columnspan=3, pady=(0, 10))

        # Frame des statistiques
        stats_frame = ttk.LabelFrame(main_frame, text="Statistiques", padding="10")
        stats_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 20))

        # Statistiques
        self.stats_labels = {}
        stats_info = [
            ("Nombres générés", "count"),
            ("Plus grand nombre", "max"),
            ("Moyenne", "avg"),
            ("Somme totale", "sum")
        ]

        for i, (label, key) in enumerate(stats_info):
            ttk.Label(stats_frame, text=f"{label} :").grid(row=i // 2, column=(i % 2) * 2, sticky=tk.W, padx=5, pady=2)
            self.stats_labels[key] = ttk.Label(stats_frame, text="0", font=('Arial', 10, 'bold'))
            self.stats_labels[key].grid(row=i // 2, column=(i % 2) * 2 + 1, sticky=tk.W, padx=5, pady=2)

        # Zone d'affichage des nombres premiers
        display_frame = ttk.LabelFrame(main_frame, text="Nombres premiers générés", padding="10")
        display_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 20))
        display_frame.columnconfigure(0, weight=1)
        display_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(6, weight=1)

        # Zone de texte avec scrollbar
        self.text_display = scrolledtext.ScrolledText(display_frame,
                                                      height=15,
                                                      width=80,
                                                      wrap=tk.WORD,
                                                      font=('Courier', 10))
        self.text_display.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Boutons d'export
        export_frame = ttk.Frame(main_frame)
        export_frame.grid(row=7, column=0, columnspan=3, pady=(10, 0))

        ttk.Button(export_frame, text="Copier dans le presse-papier",
                   command=self.copy_to_clipboard).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(export_frame, text="Sauvegarder dans un fichier",
                   command=self.save_to_file).pack(side=tk.LEFT)

    def set_count(self, value):
        """Définit rapidement le nombre de nombres premiers"""
        self.count_var.set(str(value))
        self.generate_primes_threaded()

    def is_prime(self, n):
        """Vérifie si un nombre est premier"""
        if n < 2:
            return False
        if n == 2:
            return True
        if n % 2 == 0:
            return False

        for i in range(3, int(math.sqrt(n)) + 1, 2):
            if n % i == 0:
                return False
        return True

    def generate_primes(self, count):
        """Génère les n premiers nombres premiers"""
        primes = []
        num = 2

        while len(primes) < count:
            if self.is_prime(num):
                primes.append(num)
                # Mise à jour du progrès (moins fréquente pour de gros calculs)
                if len(primes) % max(1, count // 100) == 0 or len(primes) < 100:
                    progress = (len(primes) / count) * 100
                    self.root.after(0, lambda p=progress: self.update_progress(p))
                    # Mise à jour du statut
                    self.root.after(0, lambda current=len(primes), total=count:
                    self.status_var.set(f"Génération en cours... {current}/{total} nombres trouvés"))
            num += 1

        return primes

    def update_progress(self, value):
        """Met à jour la barre de progression"""
        self.progress_var.set(value)

    def generate_primes_threaded(self):
        """Lance la génération des nombres premiers dans un thread séparé"""
        if self.is_calculating:
            return

        try:
            count = int(self.count_var.get())
            if count < 1:
                messagebox.showerror("Erreur", "Veuillez entrer un nombre positif")
                return
            if count > 100000:
                result = messagebox.askyesno("Attention",
                                             f"Vous demandez {count} nombres premiers.\n"
                                             f"Cela peut prendre beaucoup de temps et de mémoire.\n"
                                             f"Voulez-vous continuer ?")
                if not result:
                    return
        except ValueError:
            messagebox.showerror("Erreur", "Veuillez entrer un nombre valide")
            return

        self.is_calculating = True
        self.generate_button.config(state='disabled')
        self.progress_bar.config(mode='determinate')
        self.status_var.set(f"Génération de {count} nombres premiers en cours...")

        # Lancement du thread
        thread = threading.Thread(target=self.generate_and_display, args=(count,))
        thread.daemon = True
        thread.start()

    def generate_and_display(self, count):
        """Génère et affiche les nombres premiers"""
        try:
            # Génération
            self.primes = self.generate_primes(count)

            # Mise à jour de l'interface dans le thread principal
            self.root.after(0, self.display_results)

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Erreur", f"Erreur lors de la génération : {str(e)}"))
        finally:
            self.root.after(0, self.reset_ui)

    def display_results(self):
        """Affiche les résultats dans l'interface"""
        # Effacer le texte précédent
        self.text_display.delete(1.0, tk.END)

        # Afficher les nombres premiers
        text_content = f"Liste des {len(self.primes)} premiers nombres premiers :\n\n"

        # Afficher TOUS les nombres premiers, peu importe la quantité
        for i, prime in enumerate(self.primes, 1):
            text_content += f"{i:6d}: {prime:10d}"
            if i % 4 == 0:  # 4 colonnes
                text_content += "\n"
            else:
                text_content += "  "

        if len(self.primes) % 4 != 0:
            text_content += "\n"

        # Informations supplémentaires
        text_content += f"\n\n{'=' * 70}\n"
        text_content += f"Résumé détaillé :\n"
        text_content += f"• Nombres générés : {len(self.primes):,}\n"
        text_content += f"• Plus petit : {min(self.primes) if self.primes else 0:,}\n"
        text_content += f"• Plus grand : {max(self.primes) if self.primes else 0:,}\n"
        text_content += f"• Moyenne : {sum(self.primes) / len(self.primes):,.2f}\n"
        text_content += f"• Somme totale : {sum(self.primes):,}\n"

        # Informations sur les écarts
        if len(self.primes) > 1:
            gaps = [self.primes[i + 1] - self.primes[i] for i in range(len(self.primes) - 1)]
            text_content += f"• Plus petit écart : {min(gaps)}\n"
            text_content += f"• Plus grand écart : {max(gaps)}\n"
            text_content += f"• Écart moyen : {sum(gaps) / len(gaps):.2f}\n"

        self.text_display.insert(1.0, text_content)

        # Mise à jour des statistiques
        self.update_statistics()

    def update_statistics(self):
        """Met à jour les statistiques affichées"""
        if self.primes:
            self.stats_labels['count'].config(text=f"{len(self.primes):,}")
            self.stats_labels['max'].config(text=f"{max(self.primes):,}")
            self.stats_labels['avg'].config(text=f"{sum(self.primes) / len(self.primes):,.1f}")
            self.stats_labels['sum'].config(text=f"{sum(self.primes):,}")
        else:
            for label in self.stats_labels.values():
                label.config(text="0")

    def reset_ui(self):
        """Remet l'interface à l'état initial"""
        self.is_calculating = False
        self.generate_button.config(state='normal')
        self.progress_bar.config(mode='indeterminate')
        self.progress_var.set(0)
        self.status_var.set(f"✅ {len(self.primes)} nombres premiers générés avec succès !")

    def copy_to_clipboard(self):
        """Copie les résultats dans le presse-papier"""
        if not self.primes:
            messagebox.showwarning("Attention", "Aucun nombre premier à copier")
            return

        content = ", ".join(map(str, self.primes))
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        messagebox.showinfo("Succès", "Nombres premiers copiés dans le presse-papier !")

    def save_to_file(self):
        """Sauvegarde les résultats dans un fichier"""
        if not self.primes:
            messagebox.showwarning("Attention", "Aucun nombre premier à sauvegarder")
            return

        from tkinter import filedialog
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Fichiers texte", "*.txt"), ("Tous les fichiers", "*.*")]
        )

        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"Liste des {len(self.primes)} premiers nombres premiers\n")
                    f.write("=" * 50 + "\n\n")

                    for i, prime in enumerate(self.primes, 1):
                        f.write(f"{i:4d}: {prime}\n")

                    f.write(f"\nStatistiques :\n")
                    f.write(f"- Nombre total : {len(self.primes)}\n")
                    f.write(f"- Plus grand : {max(self.primes)}\n")
                    f.write(f"- Moyenne : {sum(self.primes) / len(self.primes):.2f}\n")
                    f.write(f"- Somme : {sum(self.primes)}\n")

                messagebox.showinfo("Succès", f"Fichier sauvegardé : {filename}")
            except Exception as e:
                messagebox.showerror("Erreur", f"Erreur lors de la sauvegarde : {str(e)}")


def main():
    root = tk.Tk()
    app = PrimeNumbersGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()