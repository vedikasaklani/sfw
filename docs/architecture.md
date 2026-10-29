# Architecture

The portal is a modular monolith: React/Vite talks only to a versioned FastAPI API. The API owns mapping, recommendations and portal preferences; Koha remains the system of record. SQLAlchemy persists user interests and generated recommendation metadata. SQLite is the local default and can be replaced with PostgreSQL using `DATABASE_URL`.

## System context and deployment

```mermaid
flowchart LR
  Patron -->|browser| Web[React portal]
  Web -->|HTTPS JSON /api/v1| API[FastAPI modular monolith]
  API --> DB[(Portal database)]
  API -->|server-side authorized requests| Koha[Koha REST API]
  Demo[Demo adapter] -.selected when DEMO_MODE=true.-> API
```

Deployment topology beyond the local development setup is proposed, not verified. TLS termination, database hosting, and Koha network access depend on the target library environment.

## Components

```mermaid
flowchart TB
  UI[React pages and shared components] --> Routes[Versioned API routes]
  Routes --> Services[Dashboard / catalogue / recommendation / analytics services]
  Services --> Repo[SQLAlchemy portal persistence]
  Services --> Adapter[Koha application interface]
  Adapter --> Live[Koha REST client]
  Adapter --> Mock[Clearly labelled demo adapter]
```

The implementation preserves the UML responsibilities (patron/User, catalogue Book, borrowing records, interests, strategy recommendations, analysis service, Koha client, dashboard widgets) without one class per diagram box. Since the source diagrams were not supplied, UML mapping is provisional and based on the written brief.

## Recommendation sequence

```mermaid
sequenceDiagram
  participant UI
  participant API
  participant Engine
  participant Koha
  participant DB
  UI->>API: GET recommendations
  API->>Engine: generate for authenticated patron
  Engine->>Koha: borrowing history and candidate books
  Koha-->>Engine: available authorized records
  Engine->>Engine: infer subject weights, exclude known loans, rank
  Engine->>DB: save scores and explanations
  Engine-->>API: ranked recommendations
  API-->>UI: response with source and reason
```

The demo vertical slice implements explainable subject overlap and a new-arrival/availability fallback. Live patron resolution, persistence of generated records, caching, and pagination across Koha responses remain to be wired after deployment-specific auth and endpoint verification.
