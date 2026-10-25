# Synty Store — Synchronisation de bibliothèque

## Ce que fait le script

Ce script synchronise uniquement les téléchargements autorisés de **votre bibliothèque Synty Store** via un navigateur Chromium piloté par Playwright. Il ne modifie pas le contenu du compte Synty.

- Page de bibliothèque : `.../apps/downloads/orders/<CUSTOMER_ID>`
- Pagination via le lien `.sky-pilot-pagination .next a`
- Packages via `.sky-pilot-files-list a.sky-pilot-list-item`
- Boutons de fichiers via `a.button.sky-pilot-button` vers `/apps/downloads/downloads/...`
- Connexion interactive et code reçu par e-mail lorsque nécessaire
- Sauvegarde durable de la session dans un profil Chromium local
- Sauvegarde dans `<output>/<nom du package>/<nom du fichier>` (sans extraction)
- Ne supprime jamais et n'écrase jamais les archives déjà présentes
- Historique par lien de téléchargement (`.synty_history.json`) ; si un lien a déjà été téléchargé et que le fichier existe, aucun clic/téléchargement n'est effectué
- Si un fichier est trouvé avec le même nom mais un contenu différent, une copie suffixée par l'identifiant de téléchargement est enregistrée
- Si une erreur survient, les autres fichiers sont traités et les erreurs sont tracées

## Prérequis Windows 11

Installer Python 3.10+.

Dans PowerShell, dans le dossier où se trouvent `synty_sync.py` et `synty_requirements.txt` :

```powershell
py -3 -m pip install -r .\synty_requirements.txt
py -3 -m playwright install chromium
```

## Configuration : `config.yaml`

Les identifiants et la destination sont désormais définis dans
`../config.yaml` (à la racine du dépôt, au-dessus de `SyntyDownloader`) :

```yaml
output_dir: SyntyLibrary
login:
  email: "toto"                 # Adresse e-mail Synty Store
  password: "tata"              # Utilisé seulement si un formulaire le demande
  customer_id: "4393663955098" # Identifiant déjà utilisé dans le script précédent
```

- Le chemin relatif de `output_dir` est résolu **depuis le fichier YAML**, indépendamment du répertoire depuis lequel on lance Python.
- Pour déplacer les trois dossiers sur un autre disque, conserver `SyntyLibrary`.
- Si nécessaire, copier `../config.example.yaml` vers `../config.yaml`, puis adapter les champs.
- `config.yaml` est **ignoré par Git** via le `.gitignore` à la racine. Ne jamais enregistrer de vrais identifiants dans `../config.example.yaml`.
- Synty peut demander un code à usage unique reçu par e-mail. Le mot de passe est facultatif.

Installer les nouvelles dépendances depuis `SyntyDownloader` :

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\synty_requirements.txt
```

Ou relancer `../install.cmd`, qui installe maintenant `PyYAML`.

## Utilisation

Vérifier le YAML sans lancer Chromium :

```powershell
.\.venv\Scripts\python.exe .\synty_sync.py --check-config
```

Simulation :

```powershell
.\.venv\Scripts\python.exe .\synty_sync.py --dry-run
```

Premier téléchargement limité à un seul package :

```powershell
.\.venv\Scripts\python.exe .\synty_sync.py --limit-packages 1
```

Synchronisation complète :

```powershell
.\.venv\Scripts\python.exe .\synty_sync.py --headless
```

Le lanceur autonome `run_synty_sync.cmd` exécute successivement un démarrage interactif
sur un package puis une synchronisation complète headless. Son ancien paramètre
PowerShell `-OutputDir` est accepté mais ignoré (compatibilité avec le lanceur
existant de Local Dex) : le chemin du YAML reste prioritaire. L'option Python
`--output` reste disponible pour une surcharge **manuelle**, si nécessaire.

Si la session a expiré, exécuter à nouveau la commande sans `--headless` et
entrer le code reçu par e-mail (dans la console ou Chromium). La session est
conservée dans `<output_dir>/.synty_browser_profile`.

## Structure de destination

```text
SyntyLibrary\
  ANIMATION - Base Locomotion\
    archive_1.zip
    archive_2.unitypackage
  POLYGON - Adventure Pack\
    adventure_pack.zip
  .synty_history.json          # Historique des liens utilisés
  .synty_sync.log              # Journal des actions et erreurs
  .synty_browser_profile\     # Session d'authentification du navigateur
  .synty-partials\            # Éventuels fragments de transferts échoués
```

Les fichiers sont conservés **tels que fournis par le site** ; les archives ne sont pas automatiquement extraites. Des noms différents pourront être proposés par le serveur.

## Notes importantes

- **Testé localement** sur votre fichier HTML de bibliothèque fourni : 15 packages et un lien vers la page 2. Le HTML des pages individuelles de package et la connexion réelle ne sont **pas** disponibles localement, donc un test réel avec votre compte est nécessaire.
- Le site peut changer sa structure HTML, les boutons de téléchargement ou son mécanisme d'authentification. Les sélecteurs peuvent alors nécessiter un ajustement.
- Par défaut, les téléchargements sont séquentiels avec une pause d'une seconde (`--delay 3` pour ralentir).
- Le script ne contourne pas les CAPTCHA, le contrôle d'accès, ni les limites de téléchargement imposées par le site.
- Le profil `.synty_browser_profile` contient des cookies de connexion. L'historique peut contenir votre adresse e-mail dans des URL. **Ne partagez pas ces fichiers et ne les ajoutez pas à Git**.
- Un fichier déjà référencé dans l'historique n'est pas téléchargé si son chemin est encore présent et de taille non nulle. Si vous supprimez un fichier, il sera téléchargé à nouveau au prochain lancement. Les fichiers de bibliothèque existants ne sont jamais supprimés par le script.
- Lorsqu'un fichier existant n'est *pas* encore dans l'historique, il faut recevoir le téléchargement une première fois pour connaître et comparer de manière fiable son nom et ses octets. Les synchronisations suivantes le reconnaîtront grâce à l'historique.
- Les téléchargements ayant échoué ne sont pas marqués comme réussis ; les fragments laissés dans `.synty-partials` peuvent être examinés/nettoyés manuellement.
