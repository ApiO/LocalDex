# Installation automatique Synty Sync (Windows 11)

## Installation en deux clics

1. Décompresser **entièrement** `synty_sync_windows.zip` dans un dossier, par exemple `C:\Tools\SyntySync`.
2. Double-cliquer sur `install_synty_sync.cmd`.
3. L'installateur vérifie Python (version 3.10 minimum), installe Python 3.13 via `winget` **si Python est absent ou trop ancien**, crée un environnement Python local `.venv`, installe les dépendances et installe Chromium pour Playwright.
4. Ouvrir `synty_sync.py` et remplacer `USERNAME = "toto"` par l'e-mail Synty utilisé pour la connexion. Le script demandera le code reçu par e-mail si nécessaire.
5. Double-cliquer sur `run_synty_sync.cmd` : première connexion interactive sur un package, puis synchronisation intégrale en headless.

Les fichiers téléchargés vont dans `D:\SyntyLibrary` par défaut (modifiable via la variable `$OutputDir` de `run_synty_sync.ps1`, ou via `run_synty_sync.cmd` en lui passant `-OutputDir "E:\SyntyLibrary"` depuis `cmd`).

## Sécurité PowerShell

Les fichiers `.cmd` lancent leur propre processus PowerShell avec `-ExecutionPolicy Bypass`. **Aucune modification permanente de la stratégie d'exécution du système n'est effectuée.** Aucune élévation administrateur n'est normalement nécessaire. Une stratégie d'entreprise appliquée par GPO peut toutefois continuer à bloquer l'exécution.

On n'utilise pas `Activate.ps1` de `.venv` ; l'interpréteur Python est lancé directement, ce qui évite le blocage PowerShell sur les environnements virtuels.

## En cas de problème

- Si `winget` est indisponible : installer l'application « App Installer » de Microsoft ou Python 3.13 depuis python.org, puis relancer l'installateur.
- Si Python vient d'être installé mais n'est pas trouvé : rouvrir une session Windows, puis relancer `install_synty_sync.cmd`.
- Si la destination `D:` n'existe pas : modifier `$OutputDir` dans `run_synty_sync.ps1`.
- Si le site redemande l'authentification : fermer le navigateur et relancer `run_synty_sync.cmd` pour effectuer la première étape visible.
- Relancer l'installateur est sans danger : les dépendances sont remises à jour sans supprimer les archives de la bibliothèque.

L'installeur n'efface pas les archives existantes. Le dossier `.venv` et le navigateur Chromium peuvent occuper plusieurs centaines de mégaoctets. Le profil Chromium (dans le dossier de destination) est privé et doit rester accessible uniquement à l'utilisateur du PC.
