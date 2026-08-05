INSERT INTO system.pipelines (pipeline_name, description)
VALUES
    ('attendance', 'Collect Edmingle attendance records into Bronze'),
    ('enrollment', 'Collect Edmingle student enrollment records into Bronze'),
    ('batches', 'Collect Edmingle master batches into Bronze'),
    ('catalogue', 'Collect the Edmingle course catalogue into Bronze')
ON CONFLICT (pipeline_name) DO NOTHING;

INSERT INTO system.feature_flags (feature_name, description)
VALUES
    ('scheduler', 'Allow the warehouse scheduler to claim enabled jobs'),
    ('monitoring_service', 'Enable the independently deployed monitoring service'),
    ('notification_service', 'Enable outbound operational notifications'),
    ('dashboards', 'Enable approved dashboard applications')
ON CONFLICT (feature_name) DO NOTHING;

INSERT INTO system.configuration (configuration_key, configuration_value, description)
VALUES
    ('platform_timezone', '"UTC"'::jsonb, 'Canonical timezone for stored platform timestamps')
ON CONFLICT (configuration_key) DO NOTHING;
