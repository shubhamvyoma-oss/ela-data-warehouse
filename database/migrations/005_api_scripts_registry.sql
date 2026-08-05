ALTER TABLE system.collectors RENAME TO api_scripts;
ALTER TABLE system.api_scripts RENAME CONSTRAINT collectors_pkey TO api_scripts_pkey;
ALTER TABLE system.api_scripts
    RENAME CONSTRAINT collectors_collector_name_key TO api_scripts_collector_name_key;
ALTER SEQUENCE system.collectors_id_seq RENAME TO api_scripts_id_seq;
