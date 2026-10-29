# Koha metadata for recommendations

This guide records which Koha data can support recommendations and defines the boundary between Koha and the recommendation code. It is written so contributors can work from the checked-in JSON contract and fixture without a Koha installation.

## Short version

Koha stores bibliographic records as MARC and derives some convenient JSON fields from them. It also stores item/copy data and patron checkout history separately. The fields present depend on the Koha version, MARC framework, cataloging practices, endpoint permissions, privacy settings, and whether optional MARC fields were entered.

Use `docs/recommendation-metadata.schema.json` as the versioned, source-neutral input contract and `docs/examples/recommendation-snapshot.json` as the offline example. Recommendation code should accept that contract; only `app/integrations/koha.py` should know Koha routes, authentication, MARC tags, or raw Koha key names.

## Koha sources and available metadata

### 1. Bibliographic record: work/title-level data

Main source: `GET /api/v1/biblios` and `GET /api/v1/biblios/{biblio_id}` (`catalogue: 1`). The current KTD's JSON response exposed these keys on one inspected record. Nullable fields are shown even when their value is empty; other records may populate them.

| Koha JSON field | Meaning and recommendation use |
|---|---|
| `biblio_id` | Koha record identifier. Map to the opaque portal `book_id`; do not make the engine parse it. |
| `title`, `subtitle`, `part_number`, `part_name`, `uniform_title` | Display and title matching. |
| `author` | Primary statement of responsibility. Normalize to portal `authors[]`; do not assume it contains every contributor. |
| `publication_year`, `copyright_date` | Recency, era filters, and display. Preserve an unknown year as `null`; Koha may provide a range or nonnumeric value in some catalogues. |
| `publisher`, `publication_place`, `edition_statement` | Edition and publisher context; usually secondary recommendation features. |
| `isbn`, `issn`, `ean`, `lc_control_number` | Identifiers for deduplication and external enrichment. ISBN/ISSN fields can contain multiple values or formatting differences. |
| `abstract`, `notes` | Text features for content similarity. Treat as optional, clean markup, and avoid exposing staff-only notes. |
| `item_type` | Koha's bibliographic-level item type; a useful broad material/format signal, but not necessarily the item's effective type. |
| `series_title`, `collection_title`, `collection_volume`, `collection_issn`, `volume`, `number` | Series/sequence affinity and edition grouping. |
| `pages`, `illustrations`, `material_size`, `medium`, `serial`, `serial_total_issues`, `volume_date`, `volume_description` | Format and physical characteristics; optional refinements. |
| `cn_class`, `cn_item`, `cn_suffix`, `cn_source`, `cn_sort` | Classification/call-number data; may support shelving-neighbour discovery. Treat as library-specific and never as user interest by itself. |
| `age_restriction` | Candidate eligibility/filtering signal. Apply Koha/library policy before ranking; don't infer a patron's age from it. |
| `url` | Resource link if cataloged. Validate schemes and do not ingest arbitrary page content automatically. |
| `creation_date`, `timestamp`, `framework_id`, `opac_suppressed` | Record-management/status metadata. Useful for sync and eligibility, generally not a taste signal. Exclude OPAC-suppressed records from public recommendations. |

The KTD response also included `abstract`, `author`, `biblio_id`, `cn_*`, `collection_*`, `copyright_date`, `edition_statement`, `ean`, `framework_id`, `isbn`, `issn`, `item_type`, `lc_control_number`, `material_size`, `medium`, `notes`, `number`, `opac_suppressed`, `pages`, `part_*`, `publication_*`, `publisher`, `serial*`, `series_title`, `subtitle`, `timestamp`, `title`, `uniform_title`, `url`, and `volume*`. This is an observed response shape, not a promise every Koha site returns each field.

### 2. MARC record: richer, framework-dependent cataloging

Koha can represent a biblio as MARC-in-JSON or MARCXML through content negotiation on biblio endpoints. For example, the current KTD returned a MARC-in-JSON object with `leader` and `fields` when requested with `Accept: application/marc-in-json`. That same inspected record contained tags `001`, `005`, `008`, `010`, `020`, `040`, `042`, `043`, `050`, `082`, `100`, `245`, `250`, `300`, `504`, `505`, `600`, `610`, `650`, `906`, `942`, `955`, and `999`. Another library may use a different MARC schema, framework, tags, and subfield rules.

Common MARC21 fields a mapper may use when present:

| MARC field | Typical signal |
|---|---|
| `100`, `110`, `111` | Main personal, corporate, or meeting contributor. |
| `245` | Main title (`$a`), subtitle (`$b`), responsibility (`$c`), parts (`$n`, `$p`). |
| `246` | Alternate title/title variants. |
| `020`, `022`, `024` | ISBN, ISSN, and other standard identifiers. |
| `041`, `008` | Language. `008` positions and meanings depend on the MARC schema. |
| `250` | Edition. |
| `260`, `264` | Publication place, publisher, and date. `264` indicators distinguish production, publication, distribution, manufacture, and copyright. |
| `300`, `336`, `337`, `338` | Physical extent, content type, media type, and carrier type. |
| `490`, `800`, `810`, `811`, `830` | Series statements and controlled series access points. |
| `500`, `504`, `505`, `520` | General notes, bibliography note, contents note, and summary/abstract. Notes are optional and may need public/private handling. |
| `521` | Intended audience/age note; use for eligibility only when library policy permits. |
| `600`, `610`, `611`, `630`, `648`, `650`, `651`, `653` | Subject access points (personal, organization, meeting, title, time, topical, geographic, uncontrolled). Preserve separate headings before any normalization. |
| `655` | Genre/form. Often a better format/topic signal than inferring genre from title text. |
| `700`, `710`, `711`, `720` | Added personal, corporate, meeting, and uncontrolled contributors. |
| `050`, `082`, `090` | Library of Congress, Dewey, or local classification. Local call-number patterns need site-specific treatment. |
| `856` | Electronic access URL and link text. Validate before displaying or fetching. |
| `586` | Awards/recognition note. |

These are candidate standard fields, not guaranteed populated fields. Do not hard-code MARC21 as the only supported schema. The adapter should have a versioned extractor per declared schema/framework (for example `marc21_v1`), preserve unknown fields for diagnostics only, and map known values into the portal contract. Never pass an unparsed Koha MARC dictionary to the recommendation engine.

### 3. Item/copy record: availability and local context

Main source: `GET /api/v1/biblios/{biblio_id}/items` (`catalogue: 1`), paginated. The current KTD JSON item response exposed the following fields:

| Group | Koha fields | Recommendation use |
|---|---|---|
| Identity/linkage | `item_id`, `biblio_id` | Join copy to work internally. Do not use Koha's numeric identifiers as recommendation features. |
| Material | `item_type_id`, `effective_item_type_id`, `collection_code`, `materials_notes`, `serial_issue_number`, `copy_number` | Format or edition/item-level filters; normalize codes through Koha lookup endpoints if user-facing labels are needed. |
| Library/location | `home_library_id`, `holding_library_id`, `location`, `permanent_location`, `callnumber`, `call_number_source`, `call_number_sort`, `coded_location_qualifier` | Local availability/pickup and optional shelf-neighbour signals. Library/location codes are site-specific. |
| Availability | `checked_out_date`, `not_for_loan_status`, `effective_not_for_loan_status`, `lost_status`, `withdrawn`, `damaged_status`, `restricted_status`, `new_status`, `bookable`, `effective_bookable`, `exclude_from_local_holds_priority` | Determine if a candidate is obtainable; respect Koha's effective status and portal policy. |
| Aggregate activity | `checkouts_count`, `renewals_count`, `holds_count`, `last_checkout_date`, `last_seen_date`, `acquisition_date` | Optional freshness/popularity signals. Treat counts as coarse library-wide popularity, not individual taste. These fields may be null, hidden, or inconsistent with a particular reporting window. |
| Management/private | `external_id`, `internal_notes`, `public_notes`, `acquisition_source`, `purchase_price`, `replacement_price`, `replacement_price_date`, `inventory_number`, `extended_subfields`, `timestamp` | Exclude from recommendation features. In particular, never expose or persist a barcode (`external_id`) in a recommendation payload. |

The current response additionally included `uri`, `localuse`, `shelving_control_number`, and `damaged_date`. Koha's REST schema and `x-koha-embed` options can expose related library/item-type labels, checkout, transfer, hold, and item analytics data where permitted. Request only needed embeds; don't embed a patron or checkout when a count/status field is enough.

### 4. Patron reading events and aggregate popularity

Sources already used by this repository:

| Source | Data | Use and limits |
|---|---|---|
| `GET /api/v1/checkouts?patron_id={patron_id}` | Current checkout's `item_id`, `checkout_date`, `due_date`, and item/biblio embeds. | Exclude current loans from suggestions; may infer short-term topics only with careful weighting. This is a patron-specific read. |
| `GET /api/v1/patrons/{patron_id}/checkouts` | Checkout history, including `checkout_date`, `checkin_date`, item/biblio and checkout identifiers. | Returned titles and recency are the strongest direct signals. Availability is subject to checkout-history permission, privacy and retention settings. Never send the patron ID or raw Koha response to the browser's engine code. |
| Item fields `checkouts_count`, `renewals_count`, `holds_count` | Copy-level aggregate counts if present. | Can estimate broad demand/popularity; aggregate at biblio/work level and time-normalize if feasible. Do not let popularity dominate personal preference. |
| Portal-owned, explicit interests/ratings/hides | User-entered preference or interaction. | Strong first-party signals. Keep distinct from Koha's source data, and include only after user has authenticated/consented. |

Checkout schema fields may also include `checkout_id`, `patron_id`, `item_id`, `booking_id`, `external_id`, `due_date`, `library_id`, `issuer_id`, `checkin_date`, `checkin_library_id`, `last_renewed_date`, `renewals_count`, `unseen_renewals`, `auto_renew`, `auto_renew_error`, `timestamp`, `checkout_date`, `onsite_checkout`, `note*`, and embedded `item`, `library`, `patron`, or `booking` objects. The recommendation engine needs only the linked work plus event date/type; exclude identifiers, barcodes, issuer, account notes, due dates, fines, patron profile/contact/demographic data, and staff data from its scoring input.

## Stable portal contract

The JSON Schema at [`recommendation-metadata.schema.json`](recommendation-metadata.schema.json) is the boundary between all data sources and recommendation logic. A conforming snapshot contains:

- `catalogue[]`: source-neutral `book_id`, title, authors, subjects, genres, language, year, format, description, availability, and optional aggregate popularity.
- `reader_history[]`: only the work ID and checkout/return dates needed for ranking.
- `explicit_preferences[]`: optional values the reader directly selected; never silently derived from protected demographics.
- `contract_version`: version the engine may validate before processing.

All enriching metadata is nullable or an empty list. A missing subject is not an error and must not break recommendations. `book_id` is opaque: it may be sourced from Koha `biblio_id`, a future library platform ID, or a fixture ID. Scoring must not depend on a Koha-shaped key name, MARC tag, API URL, OAuth client, or Koha availability.

### Ownership boundary

```text
Koha REST/MARC response
        |
        v
app/integrations/koha.py       Koha auth, HTTP, pagination, raw field extraction
        |
        v
RecommendationSnapshot        versioned source-neutral JSON contract
        |
        v
recommendation engine         pure ranking over snapshot; no Koha imports/network
        |
        v
recommendation result         book_id + score + explanation code/text
```

Do not modify the recommendation engine to read raw Koha records. Update the adapter to map any new Koha data into the contract, then update the schema/fixture if the contract itself needs a new optional feature. Keep Koha-specific permission and network changes inside the adapter/configuration and `docs/koha-integration.md`.

## Work offline

1. Use `docs/examples/recommendation-snapshot.json` as the input to engine work. It contains synthetic records, not a Koha export or real borrower data.
2. Write or change scoring code using only the source-neutral snapshot fields. Do not require `.env`, Docker, or a running library server.
3. Validate changed sample data against `docs/recommendation-metadata.schema.json` using any JSON Schema Draft 2020-12 validator.
4. Keep adapter changes covered by mocked Koha HTTP responses under `backend/tests`; do not make ordinary recommendation work call the live KTD.
5. If Koha adds a field, record the raw name, endpoint/permission, nullability, transformation, and privacy classification here before using it.

## Current implementation gap

`map_biblio` currently normalizes only ID, title, author, subject (when present), publication year, ISBN, abstract/notes, and a placeholder availability. The current KTD flattened biblio JSON response does not expose `subject`/`subjects`, although MARC fields such as `600`, `610`, and `650` exist on the inspected record. Therefore subject-based live recommendations need a MARC-in-JSON/MARCXML extraction step (or a verified Koha field/endpoint) before they can be considered complete. Item availability is fetched separately and current checkout history is available, but the production recommendation engine remains a separate implementation task.

## Sources

- [Koha REST API, current development reference](https://api.koha-community.org/Development.html): biblios, items, checkouts, embeds, and permission requirements.
- [Koha::Biblio API mapping](https://perldoc.koha-community.org/Koha/Biblio.html): biblio API fields and merged related biblioitem metadata.
- [Koha::Biblioitem schema](https://perldoc.koha-community.org/Koha/Schema/Result/Biblioitem.html): ISBN, ISSN, publication year, publisher, and edition/collection fields.
- [Koha::Item API mapping](https://github.com/Koha-Community/Koha/blob/main/Koha/Item.pm): item fields and effective status mappings. Verify against the deployed Koha version because this KTD is a development build.
