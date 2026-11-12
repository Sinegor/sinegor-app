const { winston } = require("@strapi/logger");

// Koa's default HTTP logger includes the raw URL. Database exceptions may include
// SQL values. Production emits classifications only; never serialize the input.
const safeEvent = winston.format((info) => ({
  level: info.level,
  [Symbol.for("level")]: info[Symbol.for("level")],
  message: `cms_${info.level}`,
}));

module.exports = {
  level: "warn",
  format: winston.format.combine(
    safeEvent(),
    winston.format.timestamp(),
    winston.format.json(),
  ),
};
