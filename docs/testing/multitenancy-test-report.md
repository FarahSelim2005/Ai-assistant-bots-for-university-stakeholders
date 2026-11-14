# Multi-tenancy test report

Run on 2026-11-15 00:17 with `python -m scripts.test_catalogue` (76 cases from `backend/tests/multitenancy_catalogue.csv`, 16.3 s). No model was called: the tests stub the models and use the separate test database.

**76 passed**, 0 failed, 0 skipped.

| Area | Cases | Passed | Failed | Skipped |
|---|---:|---:|---:|---:|
| Tenant resolution | 9 | 9 | 0 | 0 |
| Data isolation | 19 | 19 | 0 | 0 |
| Branding | 6 | 6 | 0 | 0 |
| Assistants and skills | 12 | 12 | 0 | 0 |
| Users and roles | 8 | 8 | 0 | 0 |
| Plans and usage | 3 | 3 | 0 | 0 |
| Sign-up | 5 | 5 | 0 | 0 |
| Billing | 4 | 4 | 0 | 0 |
| Console | 4 | 4 | 0 | 0 |
| Database | 3 | 3 | 0 | 0 |
| GIU unchanged | 3 | 3 | 0 | 0 |

| Id | Area | Feature | Scenario | Expected | Result | Test |
|---|---|---|---|---|---|---|
| MT-T01 | Tenant resolution | Host decides the university | Requests to giu.localhost, demo.localhost, localhost, 127.0.0.1 and an unknown host | Each host maps to its university; plain localhost and 127.0.0.1 are GIU; an unknown host maps to none | ✅ passed | `test_tenants.Resolving.test_plain_localhost_is_giu` |
| MT-T02 | Tenant resolution | Host name parsing | Host headers with upper case, a port, IPv6 brackets and a trailing dot | The bare lower-case host name is used | ✅ passed | `test_tenants.Resolving.test_host_name` |
| MT-T03 | Tenant resolution | X-Tenant header only in development | X-Tenant: demo sent with APP_ENV development and with production | Honoured only in development; ignored on a server | ✅ passed | `test_tenants.Resolving.test_tenant_header_only_in_development` |
| MT-T04 | Tenant resolution | X-Tenant ignored by the middleware on a server | A request with X-Tenant in production | The host's university answers | ✅ passed | `test_tenants.Middleware.test_x_tenant_ignored_outside_development` |
| MT-T05 | Tenant resolution | Every request carries its university | A request through the middleware to an endpoint | The endpoint sees the host's university | ✅ passed | `test_tenants.Middleware.test_tenant_reaches_the_endpoints` |
| MT-T06 | Tenant resolution | Unknown and suspended universities | Requests to an unknown host and to a suspended university | 404 for an unknown host; 403 for a suspended one | ✅ passed | `test_tenants.Middleware.test_unknown_and_suspended` |
| MT-T07 | Tenant resolution | No university outside a request | Code that asks for the current university outside a request or script | It fails loudly instead of guessing | ✅ passed | `test_tenants.Resolving.test_no_tenant_outside_a_request` |
| MT-T08 | Tenant resolution | CORS per university | Browser origins *.localhost:5173 in development and in production | Allowed only in development; the 404 for an unknown university still carries CORS headers | ✅ passed | `test_tenants.Cors.test_localhost_subdomains_only_in_development` |
| MT-T09 | Tenant resolution | CORS on errors | An unknown university's 404 seen from a browser | The response carries the CORS header so the page can show the error | ✅ passed | `test_tenants.Cors.test_unknown_university_404_carries_the_cors_header` |
| MT-I01 | Data isolation | Document search per university | Universities A and B each have a secret document; each asks for the other's | Each retrieves only its own chunks | ✅ passed | `test_tenants.AppIsolation.test_each_tenant_retrieves_only_its_own_chunks` |
| MT-I02 | Data isolation | Host decides whose data | The same request on A's and on B's host | Each sees only its own data | ✅ passed | `test_tenants.AppIsolation.test_host_decides_the_tenant` |
| MT-I03 | Data isolation | Conversations | University B asks for A's conversation id | Not found | ✅ passed | `test_tenants.AppIsolation.test_conversations_of_another_tenant_are_not_found` |
| MT-I04 | Data isolation | New conversations | A chat is started on a university's host | It belongs to that university | ✅ passed | `test_tenants.AppIsolation.test_new_conversations_belong_to_the_host_tenant` |
| MT-I05 | Data isolation | Deleting | University B removes its documents' chunks and missing files | Only B's rows go; A's chunk stays | ✅ passed | `test_tenants.AppIsolation.test_deleting_touches_only_the_current_tenant` |
| MT-I06 | Data isolation | Cross-university links refused | B writes a message into A's conversation and a rating for A's answer | The database refuses both (foreign keys include the university) | ✅ passed | `test_tenants.AppIsolation.test_database_refuses_cross_tenant_links` |
| MT-I07 | Data isolation | Same checks as the app's role | MT-I01 to MT-I06 repeated as giu_app (row-level security on) | All pass as the restricted role too | ✅ passed | `test_tenants.AppIsolationAsAppRole.test_each_tenant_retrieves_only_its_own_chunks` |
| MT-I08 | Data isolation | Row-level security: no university set | A query as giu_app without app.tenant_id | No rows are visible | ✅ passed | `test_tenants.RowLevelSecurity.test_no_tenant_set_sees_no_rows` |
| MT-I09 | Data isolation | Row-level security: forgotten WHERE | A query without a tenant filter as giu_app | Only the current university's rows | ✅ passed | `test_tenants.RowLevelSecurity.test_forgotten_where_sees_only_the_current_tenant` |
| MT-I10 | Data isolation | Row-level security: writing another's rows | giu_app inserts a row for another university | Refused | ✅ passed | `test_tenants.RowLevelSecurity.test_rows_for_another_tenant_are_refused` |
| MT-I11 | Data isolation | Row-level security: update/delete without WHERE | UPDATE and DELETE without a filter as giu_app | Only the current university's rows change | ✅ passed | `test_tenants.RowLevelSecurity.test_update_and_delete_without_where_touch_only_the_current_tenant` |
| MT-I12 | Data isolation | The app's role has no other powers | giu_app reads schema_migrations, adds a university, deletes addresses, turns row-level security off | All refused; it is not a superuser and cannot bypass row-level security | ✅ passed | `test_tenants.RowLevelSecurity.test_the_role_has_no_other_powers` |
| MT-I13 | Data isolation | The university setting is per transaction | A transaction sets A; the next one sets nothing | The setting does not leak into the next transaction | ✅ passed | `test_tenants.RowLevelSecurity.test_the_tenant_setting_ends_with_its_transaction` |
| MT-I14 | Data isolation | Connections set the university | get_connection(A) opens a transaction | app.tenant_id is A inside it | ✅ passed | `test_tenants.Connections.test_tenant_is_set_in_the_transaction` |
| MT-I15 | Data isolation | Assistants of another university | A chat on A's host names B's assistant | It cannot be used | ✅ passed | `test_tenants.AgentTables.test_an_agent_of_another_tenant_cannot_be_used` |
| MT-I16 | Data isolation | Admin: another university's assistant | A's admin changes or deletes B's assistant by its id | 404; B's assistant is unchanged | ✅ passed | `test_tenants.CrossTenantAdmin.test_another_universitys_assistant_cannot_be_changed` |
| MT-I17 | Data isolation | Admin: documents | A's admin uploads a document; B's admin lists, opens and writes into A's assistant | Stored in A's own folder; B sees nothing and cannot write to A's assistant | ✅ passed | `test_tenants.CrossTenantAdmin.test_documents_stay_with_their_university` |
| MT-I18 | Data isolation | Admin: billing | A has a subscription; B's admin opens Billing | B sees none of A's; row-level security hides A's rows from B | ✅ passed | `test_tenants.CrossTenantAdmin.test_billing_shows_only_the_own_university` |
| MT-I19 | Data isolation | Document folders per university | The documents folder of GIU and of another university | GIU in data/raw, others in data/tenants/<slug> | ✅ passed | `test_tenants.Resolving.test_data_folders` |
| MT-B01 | Branding | The university's page | GET /tenant on a university's host | Its name, short name, logo, colours, start texts, audiences and live assistants | ✅ passed | `test_tenants.AssistantsApi.test_tenant_page_data` |
| MT-B02 | Branding | Branding changes only the own university | A's admin changes name, logo and colours | Only A changes; B is unchanged | ✅ passed | `test_tenants.UniversityAdmin.test_branding_changes_only_the_own_university` |
| MT-B03 | Branding | Audiences per university | A university defines its own audiences | Its assistants and chats use them; others are refused | ✅ passed | `test_tenants.UniversityAdmin.test_audiences_are_the_universitys_own` |
| MT-B04 | Branding | Prompts in the university's name | Composed prompts for a university other than GIU | GIU's name never appears | ✅ passed | `test_skills.ComposedPrompts.test_other_universities_never_see_giu` |
| MT-B05 | Branding | Local model prompt | The short prompt for the local model at another university | It names that university | ✅ passed | `test_skills.Skills.test_local_model_prompt_has_the_university` |
| MT-B06 | Branding | CV instructions in the university's name | CV rewrite instructions for NGU | No GIU in them; NGU's name and templates; GIU's own unchanged | ✅ passed | `test_skills.ChatRouting.test_cv_instructions_in_the_universitys_name` |
| MT-A01 | Assistants and skills | Create change and hide | A's admin creates an assistant from the HR template; B's admin lists assistants; chats are started | Only A sees it; staff only as the template says; B cannot open it (404) | ✅ passed | `test_tenants.AssistantsApi.test_create_change_and_hide` |
| MT-A02 | Assistants and skills | Readable unique folders | Two assistants with the same name | Each gets its own readable folder | ✅ passed | `test_tenants.AssistantsApi.test_folders_are_readable_and_unique` |
| MT-A03 | Assistants and skills | Skills like GIU | New assistants from scratch and from the Internship & Career and Labs templates | Usual skills; CV rewrites for Internship & Career; no campus map without one | ✅ passed | `test_tenants.AssistantsApi.test_new_assistants_skills_like_giu` |
| MT-A04 | Assistants and skills | Assistant made from scratch | An assistant with only a name, description, instructions and audiences | Made with its own readable folder, placed after the others | ✅ passed | `test_tenants.AssistantsApi.test_custom_assistant_without_template` |
| MT-A05 | Assistants and skills | Bad settings refused | Unknown skills, audiences, answer modes, prompt modes or templates | 400 | ✅ passed | `test_tenants.AssistantsApi.test_refused_settings` |
| MT-A06 | Assistants and skills | Deleting keeps the data | An admin deletes an assistant | It is hidden everywhere; its chats and documents are kept | ✅ passed | `test_tenants.UniversityAdmin.test_delete_keeps_the_data_and_order` |
| MT-A07 | Assistants and skills | CV rewrites at every university | "fix my cv" with a CV at GIU and at another university; and without the cv skill | CV rewrite (PDF and Word) at both; an ordinary edit without the skill | ✅ passed | `test_skills.ChatRouting.test_cv_rewrite_at_every_university` |
| MT-A08 | Assistants and skills | CV skill works without a trained model | Career assistant at a university without its own CV model | It is a CV assistant | ✅ passed | `test_skills.Skills.test_cv_skill_at_every_university` |
| MT-A09 | Assistants and skills | Campus map only where there is one | The map skill at GIU and at a university without a campus map | Shown only at GIU | ✅ passed | `test_skills.Skills.test_map_only_with_the_skill_and_a_campus_map` |
| MT-A10 | Assistants and skills | Attachments need their skill | Files and pictures sent to assistants without the files/images skill | Refused | ✅ passed | `test_skills.Skills.test_attachments_need_their_skill` |
| MT-A11 | Assistants and skills | Editor only with its skill | A document edit asked of an assistant without the editor skill | Answered as a question, not edited; the edit route refuses | ✅ passed | `test_skills.ChatRouting.test_editing_route_refused_without_the_editor_skill` |
| MT-A12 | Assistants and skills | Assistants cache per university | Rows of one university change | Only its assistants are reloaded | ✅ passed | `test_agents.Registry.test_cache_reloads_only_when_rows_change` |
| MT-U01 | Users and roles | Login per university | A user logs in on their university's host and on another's | Works only on their own | ✅ passed | `test_tenants.AdminLogins.test_a_login_works_only_for_its_own_tenant` |
| MT-U02 | Users and roles | Email and password logins | A login, a wrong password, A's user on B's host, a token on B, logout | Only the right password on its own host; the token works only on A and ends at logout | ✅ passed | `test_tenants.UniversityAdmin.test_login_with_email_and_password` |
| MT-U03 | Users and roles | Users of a university | A's admin adds an editor; B lists users; a short password; the same email; demoting the last admin | Only A sees its user; refused; 409; the last admin cannot be removed or demoted | ✅ passed | `test_tenants.UniversityAdmin.test_users_of_a_university` |
| MT-U04 | Users and roles | Another university's token | A token of university A used on B's admin; a platform owner's token on an admin page | 401 | ✅ passed | `test_admin.AdminRoutes.test_another_universitys_login_is_refused` |
| MT-U05 | Users and roles | Editors | An editor manages documents and tries assistants and branding | Documents allowed; the rest refused | ✅ passed | `test_admin.AdminRoutes.test_editors_manage_documents_only` |
| MT-U06 | Users and roles | Expired sessions | A token after its expiry | 401 | ✅ passed | `test_admin.AdminRoutes.test_expired_token` |
| MT-U07 | Users and roles | Own password | A user changes their password with a wrong and a right current password | Only the right one works | ✅ passed | `test_tenants.AdminAnalytics.test_change_own_password` |
| MT-U08 | Users and roles | Analytics per university | Questions, unanswered and ratings for A and B | Each sees only its own numbers | ✅ passed | `test_tenants.AdminAnalytics.test_questions_unanswered_and_ratings` |
| MT-P01 | Plans and usage | Usage logged per university | A model call made for university A | Logged for A with its tokens and cost; B sees none | ✅ passed | `test_tenants.PlansAndUsage.test_model_calls_are_logged_per_university` |
| MT-P02 | Plans and usage | Monthly token cap | A university reaches its plan's monthly cap | Its chat answers 429 before any search or model call; others are not affected | ✅ passed | `test_tenants.PlansAndUsage.test_monthly_cap` |
| MT-P03 | Plans and usage | Assistants per plan | A university on a 2-assistant plan adds a third | Refused; deleted ones do not count | ✅ passed | `test_tenants.PlansAndUsage.test_plan_limits_assistants` |
| MT-S01 | Sign-up | Account rules | Personal email, non-public plan, short password; then a valid sign-up | Refused; then a code is emailed and only its hash is stored | ✅ passed | `test_billing.SignupAndBilling.test_account_rules` |
| MT-S02 | Sign-up | Email code | Wrong codes, too many tries, a new code within a minute, an expired code | Tries counted (5); resend limited; expired after 10 minutes | ✅ passed | `test_billing.SignupAndBilling.test_code_tries_and_expiry` |
| MT-S03 | Sign-up | Free trial sign-up | Reserved address, too many assistants, then a valid trial | Refused, refused, then the university exists with its assistants and colours; one university per email domain | ✅ passed | `test_billing.SignupAndBilling.test_trial_then_paused_then_paid` |
| MT-S04 | Sign-up | Review before going live | Require review is on and a university signs up | It waits (403 'being set up'), no login link; approved in the console it opens | ✅ passed | `test_billing.SignupAndBilling.test_review_before_going_live` |
| MT-S05 | Sign-up | Email sending | The code email with an SMTP server and without one | STARTTLS then login then send; without SMTP_HOST only logged | ✅ passed | `test_mail.Sending.test_starttls_then_login_then_send` |
| MT-BL01 | Billing | Paid sign-up and its lifecycle | Payment fails then succeeds; renewal paid; renewal fails twice; pay now; cancel | Not made, then made; active; past_due with 7 days' grace then paused; active again; ends at period end | ✅ passed | `test_billing.SignupAndBilling.test_paid_signup_renewals_grace_and_cancel` |
| MT-BL02 | Billing | Trial ends then paid | A trial passes its end; the admin chooses Standard and pays | Chat paused; then active on Standard; going back to the trial refused | ✅ passed | `test_billing.SignupAndBilling.test_trial_then_paused_then_paid` |
| MT-BL03 | Billing | Webhook security | A forged signature, an unknown provider, the same event twice | 400, 404, applied once | ✅ passed | `test_billing.SignupAndBilling.test_webhook_signature_and_repeats` |
| MT-BL04 | Billing | Plans and trial extension | Price changed in the console; trial priced; unknown plan; trial extended after it ended | Sign-up shows the new price; refused; 404; trialing again | ✅ passed | `test_billing.SignupAndBilling.test_console_plans_and_trial_extension` |
| MT-C01 | Console | Owner login and the universities list | The console without login on a server and in development; the list | 401 on a server, open in development; every university with its numbers | ✅ passed | `test_tenants.PlatformConsole.test_login_and_universities` |
| MT-C02 | Console | Add by hand | The wizard with own and ready-made assistants; taken address; too many assistants; bad colour | The university, its address, assistants and admin are made at once; refusals | ✅ passed | `test_tenants.PlatformConsole.test_new_university_wizard` |
| MT-C03 | Console | Suspend and reactivate | The owner suspends then reactivates university B | B answers 403, A is not affected; B works again | ✅ passed | `test_tenants.PlatformConsole.test_suspend_and_reactivate` |
| MT-C04 | Console | Delete a university for good | Wrong confirmation; failed backup; confirmed delete | Refused; nothing deleted; every row and file of it gone, others untouched, its address and email free again | ✅ passed | `test_billing.SignupAndBilling.test_delete_university_for_good` |
| MT-D01 | Database | Migrations in order | The migration files | Numbered, well named, applied once each in its own transaction | ✅ passed | `test_migrate.Applying.test_only_pending_files_run_each_in_its_own_transaction` |
| MT-D02 | Database | Templates match the code | The agent_templates table | Same as the code's templates | ✅ passed | `test_tenants.AgentTables.test_templates_are_the_codes_templates` |
| MT-D03 | Database | University settings | GIU's and a new university's settings | GIU: short name, CV model, campus map, logo, colours; a new one: none of them, its short name is its name | ✅ passed | `test_tenants.AgentTables.test_tenant_settings` |
| MT-G01 | GIU unchanged | GIU's assistants | GIU's four assistants loaded from the database | Same prompts, models and rules as before multi-tenancy | ✅ passed | `test_agents.GiuAssistants.test_same_prompts_models_and_rules` |
| MT-G02 | GIU unchanged | GIU's fixed ids | GIU's assistants in the database | The four assistants with their fixed ids | ✅ passed | `test_tenants.AgentTables.test_giu_has_the_four_assistants_with_fixed_ids` |
| MT-G03 | GIU unchanged | GIU's prompts | GIU's composed prompts | Exactly as before | ✅ passed | `test_skills.ComposedPrompts.test_giu_is_unchanged` |
