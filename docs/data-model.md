# Data model

Koha owns bibliographic records, item availability, patron identity and circulation. Portal SQLAlchemy tables are deliberately narrow:

```mermaid
erDiagram
  USER ||--o{ USER_INTEREST : has
  USER ||--o{ RECOMMENDATION : receives
  USER { int id PK string name string email string koha_borrower_id }
  USER_INTEREST { int id PK int user_id FK string subject float weight datetime updated_at }
  RECOMMENDATION { int id PK int user_id FK string book_id float score string reason string strategy datetime generated_at }
  KOHA_BOOK { string biblio_id PK string title }
  KOHA_BOOK ||--o{ BORROWING : "Koha authoritative source"
  USER ||--o{ BORROWING : "resolved by Koha borrower mapping"
```

`KOHA_BOOK` and `BORROWING` in the diagram describe external Koha resources, not local tables. The current local SQL schema contains `users`, `user_interests`, and `recommendations`; the sample user's borrower mapping is only populated in demo mode. Schema creation is currently at application startup; Alembic migrations remain a delivery task.

## Loan states

Koha controls these transitions. The portal displays observed circulation status and does not implement circulation state changes.

```mermaid
stateDiagram-v2
  [*] --> Available
  Available --> Requested: hold accepted by Koha
  Requested --> Issued: checkout accepted by Koha
  Available --> Issued: checkout accepted by Koha
  Issued --> Overdue: due date passes without check-in
  Issued --> Returned: check-in recorded by Koha
  Overdue --> Returned: check-in recorded by Koha
  Returned --> Available: item reshelved by library
  Issued --> Lost: loss recorded by library in Koha
```
