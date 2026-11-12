# Enterprise Knowledge AI

Enterprise Knowledge AI est un prototype de recherche documentaire assistée par IA (RAG). Importez un PDF, posez une question en français et ouvrez la page citée pour vérifier la réponse. Chaque source affiche aussi le passage utilisé. Quand les documents ne permettent pas de répondre, l’application peut s’abstenir.

## Démarrage

**Prérequis** — Docker avec Compose v2 et une clé OpenAI API autorisée à utiliser `text-embedding-3-small` et `gpt-5-mini`. Les appels d’indexation et de génération sont facturés selon votre compte.

Depuis la racine du dépôt :

```bash
cp .env.example .env
# Renseigner OPENAI_API_KEY dans .env, puis lancer :
docker compose up --build -d
docker compose ps
```

Ouvrir [localhost:3000](http://localhost:3000). Seule l’interface est publiée sur la boucle locale. PostgreSQL, RustFS et FastAPI restent sur le réseau Docker. La clé OpenAI est lue par FastAPI et `.env` est ignoré par Git.

```bash
docker compose logs -f api   # Suivre les erreurs d’import ou de génération
docker compose down          # Arrêter les services en conservant les données
```

Les volumes `postgres` et `objects` conservent respectivement l’index et les originaux. `docker compose down -v` supprime les deux volumes et tous les documents importés.

## Démo

1. Importer [le PDF fictif de remboursement](demo/politique-remboursement.pdf). La page 1 décrit la France et la page 2 la Suisse.
2. Choisir **Utiliser une question d’exemple**, puis **Poser la question**. La réponse attendue indique un délai de **30 jours à compter de la livraison**, une demande via le portail d’assistance et la facture ainsi que le numéro de commande.
3. Cliquer sur **politique-remboursement.pdf · page 2** pour vérifier le texte dans le PDF. Le lecteur du navigateur reçoit le fragment `#page=2`.
4. Poser « Quel délai de remboursement s’applique aux clients canadiens ? ». Le PDF ne couvre pas ce pays. Le résultat attendu est une abstention sans source.

## Architecture

```mermaid
flowchart LR
    Browser["Navigateur"] --> Next["Next.js"]
    Next --> API["FastAPI"]
    API --> Split["pypdf + LlamaIndex"]
    API --> DB["PostgreSQL + pgvector"]
    API --> Storage["Stockage S3 privé · RustFS en local"]
    API --> OpenAI["OpenAI · embeddings + Responses API"]
```

| Étape | Implémentation |
| --- | --- |
| Import | FastAPI valide la taille et le type du fichier. pypdf extrait le texte page par page. LlamaIndex découpe le texte en passages de 360 tokens avec un chevauchement de 45 tokens. Chaque passage garde la page physique, comptée à partir de 1. |
| Indexation | OpenAI produit les vecteurs par lots. PostgreSQL enregistre les passages, leurs vecteurs et les termes plein texte. Le PDF original est stocké dans RustFS via l’API S3. L’import devient visible quand le stockage et la transaction PostgreSQL aboutissent. |
| Recherche | pgvector classe les passages par distance cosinus. La recherche plein texte PostgreSQL classe les passages qui partagent des termes avec la question, avec normalisation française. Reciprocal Rank Fusion fusionne jusqu’à 20 candidats de chaque branche. Les cinq premiers passages alimentent la génération. |
| Génération | GPT‑5 mini reçoit la question et les passages sélectionnés. La réponse structurée contient le texte et des identifiants de passages. FastAPI vérifie que tous les identifiants appartiennent au contexte fourni, puis reconstruit la référence depuis la base. Les citations sont contrôlées structurellement. Le lien entre une affirmation et le passage reste à vérifier dans le PDF. |

### Routes HTTP

Les routes suivantes sont accessibles via Next.js sur le port 3000.

| Méthode | Route | Effet |
| --- | --- | --- |
| `POST` | `/api/documents` | Importe le fichier multipart `file` et renvoie ses métadonnées une fois l’indexation terminée. |
| `GET` | `/api/documents` | Liste les documents indexés. |
| `GET` | `/api/documents/{id}/pdf` | Lit l’original depuis S3 et sert le PDF en ligne. |
| `POST` | `/api/ask` | Accepte `{"question": "..."}` et renvoie le texte, les citations et la durée côté API en millisecondes. |

```bash
curl --fail-with-body -F 'file=@demo/politique-remboursement.pdf' \
  http://localhost:3000/api/documents
curl --fail-with-body -H 'Content-Type: application/json' \
  -d '{"question":"Quelle est la procédure de remboursement en Suisse ?"}' \
  http://localhost:3000/api/ask
```

## Vérification

GitHub Actions démarre la stack Docker Compose, vérifie la page d’accueil et lance le test d’intégration FastAPI avec PostgreSQL 17 et pgvector. Le test simule les réponses d’OpenAI au niveau HTTP et utilise Moto pour S3. Il contrôle le rejet d’un fichier invalide, l’import du PDF fictif, le classement suisse, la citation page 2, l’intégrité du PDF servi et le rejet d’une citation inventée. Ces tests s’exécutent sans clé et sans frais OpenAI.

Pour lancer le test localement, utiliser une instance PostgreSQL de test avec pgvector et un utilisateur autorisé à créer un schéma et l’extension.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r api/requirements-test.txt
TEST_DATABASE_URL='postgresql://user:password@localhost:5432/knowledge' \
  python -m unittest discover -s api -v
```

Pour compiler l’interface en local avec Node.js 22 :

```bash
cd web
npm ci
npm run build
```

## Périmètre du prototype

- **Démonstration locale, un espace sans authentification.** Utiliser des données fictives. Avant tout accès partagé, ajouter une authentification et des autorisations pour la recherche, les citations et l’ouverture des originaux.
- **PDF textuels uniquement.** Un fichier à la fois, jusqu’à 8 Mio, 100 pages et 500 passages. Les PDF scannés sans couche texte demandent un OCR. L’indexation se déroule pendant la requête HTTP.
- **Données envoyées à OpenAI.** L’API d’embeddings reçoit le texte des passages et les questions. L’API de génération reçoit la question et les cinq passages sélectionnés. L’application configure `store: false` pour la génération. Les règles de conservation du fournisseur restent applicables. [Contrôles des données OpenAI](https://developers.openai.com/api/docs/guides/your-data)
- **Recherche hybride avec classement exact.** Le prototype affiche la latence de la requête courante. Le reranking par cross-encoder, les permissions, l’historique, les versions et le benchmark de Recall@5, précision des citations, taux de réponses justifiées, p95 et coût par question font partie des extensions du projet.
