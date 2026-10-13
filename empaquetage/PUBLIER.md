# Publier Éclipse Studio (gratuit)

Guide pas à pas pour mettre le logiciel à disposition de tous, avec des
versions installables Windows, macOS et Linux construites automatiquement.

## 1. Créer le dépôt (une seule fois)

1. Créez un compte gratuit sur https://github.com, s'il n'existe pas.
2. Cliquez sur **New repository** :
   - nom : `eclipse-studio` ;
   - visibilité : **Public** (indispensable pour que la construction soit gratuite) ;
   - ne cochez rien d'autre : la licence et le README sont déjà fournis.
3. Envoyez le dossier `EclipseStudio`. Deux façons de le faire :
   - **Sans ligne de commande** : installez GitHub Desktop (https://desktop.github.com), puis *File › Add local repository*, choisissez le dossier, *Publish repository*.
   - **En Terminal** :
     ```bash
     cd ~/Developer/EclipseStudio
     git init && git add . && git commit -m "Éclipse Studio 1.0.0"
     git branch -M main
     git remote add origin https://github.com/VOTRE-COMPTE/eclipse-studio.git
     git push -u origin main
     ```
   Le fichier `.gitignore` exclut déjà `.venv`, les constructions et les images de contrôle.

## 2. Publier une version

1. Sur la page du dépôt : **Releases › Draft a new release**.
2. *Choose a tag* : tapez `v1.0.0`, puis *Create new tag*.
3. Titre : `Éclipse Studio 1.0.0`, puis cliquez sur **Publish release**.
4. Attendez 10 à 20 minutes. L'onglet **Actions** montre l'avancement des constructions, chacune vérifiée par l'auto-test.
5. Les 5 fichiers apparaissent ensuite dans la Release : `.zip` Windows, deux `.dmg` Mac, `.tar.gz` Linux, et le **kit portable** `…-portable.zip`.

Pour une nouvelle version : changez `__version__` dans `eclipse_studio/__init__.py`, envoyez les modifications, puis créez une Release `v1.0.1`.

Pour faire un essai sans publier : *Actions › Construire › Run workflow*. Les fichiers sont alors dans *Artifacts*, en bas de la page d'exécution.

## 3. Lien à partager

`https://github.com/VOTRE-COMPTE/eclipse-studio/releases/latest`

Ce lien pointe toujours vers la dernière version. Mettez-le sur jerem-ia.fr, sur les forums (Webastro, AstroSurf, Cloudy Nights, Reddit r/astrophotography) et sous vos vidéos.

## 4. Signature et notarisation Apple (versions Mac sans avertissement)

Avec ton compte Apple Developer, les `.dmg` s'ouvrent par simple double-clic.

### Une seule fois : certificat et mot de passe

1. **Certificat « Developer ID Application »** : Xcode › Réglages › Comptes › ton compte › *Gérer les certificats* › **+** › *Developer ID Application*.
   (Seul le titulaire du compte, l'« Account Holder », peut le créer.)
   Vérification dans le Terminal : `security find-identity -v -p codesigning` doit afficher `Developer ID Application: … (TEAMID)`.
2. **Team ID** : sur https://developer.apple.com/account, rubrique *Membership details* (10 caractères).
3. **Mot de passe pour app** : sur https://account.apple.com, rubrique *Connexion et sécurité* › *Mots de passe pour app*. Crée-en un nommé « notarisation ».
4. **Enregistrer la notarisation sur ton Mac** (une fois) :
   ```bash
   xcrun notarytool store-credentials eclipse-studio \
     --apple-id TON@MAIL --team-id TON_TEAM_ID --password xxxx-xxxx-xxxx-xxxx
   ```

### Sur ton Mac

Double-clic sur `empaquetage/Construire la version Mac.command`. Le script trouve tout seul le certificat dans ton trousseau. Il signe chaque binaire de l'app (avec le runtime renforcé), notarise le `.dmg` auprès d'Apple, puis agrafe le ticket.
Il faut les outils en ligne de commande Xcode (`xcode-select --install`, s'ils manquent).

### Sur GitHub (construction automatique)

Ajoute ces secrets dans *Settings › Secrets and variables › Actions › New repository secret* :

| Secret | Contenu |
|---|---|
| `MAC_CERT_P12` | Le certificat exporté en base64. Dans *Trousseau d'accès*, fais un clic droit sur « Developer ID Application… » › *Exporter* au format `.p12`, avec un mot de passe. Ensuite : `base64 -i certificat.p12 \| pbcopy`, puis colle le résultat. |
| `MAC_CERT_MDP` | Le mot de passe choisi à l'export du `.p12` |
| `MAC_SIGNATURE` | Le nom exact affiché par `security find-identity`, ex. `Developer ID Application: Jérémy BEAUFRERE (ABCDE12345)` |
| `APPLE_ID` | L'adresse de ton compte Apple Developer |
| `APPLE_TEAM_ID` | Ton Team ID |
| `APPLE_MDP_APP` | Le mot de passe pour app |

Les secrets ne sont jamais visibles, ni dans le code ni dans les journaux. Supprime le fichier `.p12` de ton Mac une fois le secret ajouté.
Sans ces secrets, la construction fonctionne quand même, mais l'app Mac n'est pas signée.
