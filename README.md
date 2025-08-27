# V3.0 du projet nb_premier

## Présentation
**nb_premier** est une application de génération et de visualisation des nombres premiers.  
Elle repose sur un crible segmenté optimisé en mémoire via `numpy.memmap`, et intègre une interface graphique moderne réalisée avec **PySide6 (Qt6)**.  

Cette version **V3.0** se distingue par une meilleure performance, une interface sombre soignée, et des outils avancés d’exportation et de navigation.

---

## Optimisations principales

### Calcul des bornes
- Implémentation d’une **borne supérieure affinée** pour le n-ième nombre premier.
- Ajustements dynamiques selon l’ordre de grandeur (10⁵, 10⁶, 10⁹, etc.).

### Gestion mémoire & disque
- Utilisation de **`numpy.memmap`** pour stocker les grands ensembles de nombres premiers :
  - Permet de manipuler plusieurs milliards d’entrées sans saturer la RAM.
  - Chaque session génère un fichier temporaire unique (`primes_memmap_PID_TIMESTAMP.dat`).
- Vérification proactive de l’espace disque avant lancement du calcul.

### Génération multi-thread
- Calcul des nombres premiers réalisé dans un **QThread** (`PrimeGenThread`).
- Communication asynchrone via signaux Qt :
  - `progress(found, total)`
  - `finished_ok(n_found, pmax, sum, avg)`
  - `failed(message)`
  - `status_update(message)`
- Arrêt contrôlé et sûr (`.stop()`).

### Export optimisé
- Export en **.txt** via un **thread dédié** (`ExportThread`) :
  - Écriture en blocs de 10M valeurs.
  - Tampon disque de 16 Mio → réduction drastique des appels système.
  - Export interrompable proprement.

---

## Interface graphique (UI/UX)

### Thème sombre global
- Palette sombre inspirée de **Material Design**.
- Application d’un **QSS global** :
  - Boutons arrondis avec effets de survol.
  - `QTableView` sombre avec lignes alternées.
  - `QProgressBar` fluide avec chunks arrondis.
  - `QGroupBox` élégants et homogènes.
- Patch spécifique pour popups :
  - `QMessageBox`, `QFileDialog`, `ExportDialog` → fond sombre uniforme.

### Navigation
- **Tableau paginé** (`PrimePagedModel`) avec 10M lignes par page.
- Navigation fluide : `◀ Précédent`, `Suivant ▶`, `Aller à l’index`.
- Affichage dynamique `Page X/Y`.

### Statistiques
- Compteurs dynamiques :
  - Nombre de valeurs générées.
  - Plus grand nombre.
  - Somme totale.
  - Moyenne.
- Mise à jour en temps réel pendant la génération.

### Paramètres & raccourcis
- Entrée libre du nombre `N` à générer.
- **Boutons rapides** : 10, 100, 1 000, …, 1 milliard.
- Génération **adaptative** :
  - Ajustement du `segment_size` et `update_interval` selon la taille de `N`.

### Export interactif
- Popup `Export en cours` avec :
  - Barre de progression.
  - Bouton `Arrêter`.
  - Message de succès ou erreur à la fin.

---

## Fonctionnalités principales
- Génération **ultra-rapide** des nombres premiers jusqu’à `N`.
- **Interface Qt moderne** et responsive.
- **Pagination** massive pour explorer les nombres premiers.
- **Export optimisé** en `.txt`.
- **Thème sombre complet** (incluant toutes les popups).
- **Arrêt contrôlé** du calcul en cours.

---

#### by Enzo
