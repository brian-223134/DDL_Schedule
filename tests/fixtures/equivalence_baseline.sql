CREATE TABLE `teams` (
  `id` BIGINT NOT NULL,
  `name` VARCHAR(64) NOT NULL,
  PRIMARY KEY (`id`)
);

CREATE TABLE `users` (
  `id` BIGINT NOT NULL,
  `team_id` BIGINT NULL,
  `email` VARCHAR(255) NOT NULL,
  `name` VARCHAR(64) NOT NULL,
  `legacy_status` VARCHAR(32) NULL,
  PRIMARY KEY (`id`)
);

INSERT INTO `teams` (`id`, `name`) VALUES
  (1, 'Platform'),
  (2, 'Product');

INSERT INTO `users` (`id`, `team_id`, `email`, `name`, `legacy_status`) VALUES
  (1, 1, 'kim@example.com', 'Kim', 'active'),
  (2, 2, 'lee@example.com', 'Lee', 'active'),
  (3, NULL, 'park@example.com', 'Park', 'pending');
