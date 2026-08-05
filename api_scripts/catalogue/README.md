# Course catalogue collector

Collects the institute catalogue from
`GET /institute/{institute_id}/courses/catalogue?institution_id={institute_id}`.

`EDMINGLE_INSTITUTE_ID` is required. The confirmed response contract is the top-level
`response` list, including a valid empty list. Raw catalogue records are stored in Bronze; the
catalogue/batch merge and all business labels belong in Silver or Gold processing.
