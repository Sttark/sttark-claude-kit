// Every test file gets its own database in memory; nothing touches data/.
process.env.KIT_DB = ':memory:';
