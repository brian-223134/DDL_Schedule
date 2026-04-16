CREATE TABLE `audit_events` (
  `id` BIGINT NOT NULL,
  `event_type` VARCHAR(64) NOT NULL,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`)
);

ALTER TABLE `users`
  ADD COLUMN `nickname` VARCHAR(64) NULL;

CREATE INDEX `idx_users_nickname` ON `users` (`nickname`);

ALTER TABLE `users`
  ADD COLUMN `required_code` VARCHAR(32) NOT NULL DEFAULT 'legacy';

INSERT INTO `audit_events` (`id`, `event_type`, `created_at`) VALUES
  (1, 'bootstrap', '2026-04-16 00:00:00');

UPDATE `users`
SET `nickname` = `name`
WHERE `nickname` IS NULL;

ALTER TABLE `users`
  ADD CONSTRAINT `fk_users_team`
  FOREIGN KEY (`team_id`) REFERENCES `teams` (`id`);

CREATE UNIQUE INDEX `uq_users_email` ON `users` (`email`);

ALTER TABLE `users`
  DROP COLUMN `legacy_status`;
