-- 人脸考勤系统：非破坏性建库建表，保留已有数据。
CREATE DATABASE IF NOT EXISTS `face_attendance` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `face_attendance`;
CREATE TABLE IF NOT EXISTS app_settings (
	`key` VARCHAR(60) NOT NULL,
	value TEXT NOT NULL,
	PRIMARY KEY (`key`)
);

CREATE TABLE IF NOT EXISTS users (
	id INTEGER NOT NULL AUTO_INCREMENT,
	username VARCHAR(60) NOT NULL,
	employee_no VARCHAR(40) NOT NULL,
	name VARCHAR(60) NOT NULL,
	department VARCHAR(80) NOT NULL,
	`role` VARCHAR(16) NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	active BOOL NOT NULL,
	session_version INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (username),
	UNIQUE (employee_no)
);

CREATE TABLE IF NOT EXISTS attendance (
	id INTEGER NOT NULL AUTO_INCREMENT,
	user_id INTEGER NOT NULL,
	work_date DATE NOT NULL,
	check_in DATETIME,
	check_out DATETIME,
	in_score FLOAT,
	out_score FLOAT,
	in_status VARCHAR(20),
	out_status VARCHAR(20),
	shift_start VARCHAR(5) NOT NULL,
	shift_end VARCHAR(5) NOT NULL,
	grace_minutes INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_attendance_user_date UNIQUE (user_id, work_date),
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS audit_events (
	id INTEGER NOT NULL AUTO_INCREMENT,
	actor_id INTEGER NOT NULL,
	action VARCHAR(40) NOT NULL,
	target VARCHAR(80) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS face_templates (
	user_id INTEGER NOT NULL,
	encrypted_features BLOB NOT NULL,
	model_version VARCHAR(60) NOT NULL,
	sample_count INTEGER NOT NULL,
	enrolled_at DATETIME NOT NULL,
	PRIMARY KEY (user_id),
	FOREIGN KEY(user_id) REFERENCES users (id)
);
