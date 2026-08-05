# Processing Engine

Processing promotes committed Bronze records into approved Silver and Gold models. It never calls source APIs and never mutates Bronze.

The supplied attendance and course/batch scripts currently mix collection with cleaning, filtering, summaries, and business rules. Their collection contracts have been separated into `collectors/`; transformation logic will be implemented here after output grains, validation rules, and KPI definitions are approved.
