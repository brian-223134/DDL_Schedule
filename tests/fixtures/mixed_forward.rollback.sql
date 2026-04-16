-- Rollback pair used to infer that the forward ENUM change is an expansion.
ALTER TABLE `surveys`
  MODIFY COLUMN `type` ENUM('REGULAR') NOT NULL;

ALTER TABLE `users`
  DROP COLUMN `nickname`;

DELETE FROM `audit_events`
WHERE `event_type` = 'bootstrap;still-one-statement';
