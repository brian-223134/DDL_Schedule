-- Representative migration with statements that should land in every phase.
CREATE TABLE `audit_events` (
  `id` BIGINT NOT NULL PRIMARY KEY,
  `event_type` VARCHAR(64) NOT NULL,
  `created_at` DATETIME NOT NULL
);

ALTER TABLE `users`
  ADD COLUMN `nickname` VARCHAR(64) NULL;

CREATE INDEX `idx_users_nickname` ON `users` (`nickname`);

INSERT INTO `audit_events` (`id`, `event_type`, `created_at`)
VALUES (1, 'bootstrap;still-one-statement', NOW());

UPDATE `users`
SET `nickname` = `name`
WHERE `nickname` IS NULL;

ALTER TABLE `users`
  ADD COLUMN `required_code` VARCHAR(32) NOT NULL;

ALTER TABLE `request_schedule`
  DROP COLUMN `legacy_status`;

ALTER TABLE `child`
  ADD CONSTRAINT `fk_child_parent`
  FOREIGN KEY (`parent_id`) REFERENCES `parent` (`id`);

CREATE UNIQUE INDEX `uq_users_email` ON `users` (`email`);

ALTER TABLE `users`
  ADD COLUMN `display_name` VARCHAR(64) NULL,
  DROP COLUMN `legacy_name`;

ALTER TABLE `users`
  RENAME COLUMN `nickname` TO `display_name`;

CREATE TRIGGER `trg_users_audit`
AFTER INSERT ON `users`
FOR EACH ROW
INSERT INTO `audit_events` (`id`, `event_type`, `created_at`)
VALUES (NEW.id, 'user_created', NOW());

ALTER TABLE `surveys`
  MODIFY COLUMN `type` ENUM('REGULAR', 'CURRICULUM') NOT NULL;
