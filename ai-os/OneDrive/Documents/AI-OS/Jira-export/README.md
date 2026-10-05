# Jira export

Only needed if the Copilot Jira connector is not available or a pull looks short.

In Jira: open your saved filter for the project, then Export > Export CSV (current fields). Save it here. Include these columns: Issue key, Summary, Status, Issue Type, Priority, Assignee, Created, Updated, Due date, Labels, Flagged.

Then say `refresh dashboard` in Cowork. It uses the newest CSV in this folder.
