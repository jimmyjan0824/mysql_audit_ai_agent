-- expect: review
-- rules: L10
-- A busy event table with an INT key runs out at 2,147,483,647.
CREATE TABLE page_views (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  path VARCHAR(255) NOT NULL,
  viewed_at DATETIME NOT NULL
) DEFAULT CHARSET=utf8mb4;
