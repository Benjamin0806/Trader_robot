# 🔒 Security Policy

## Critical: Protect Your API Keys!

**NEVER commit your API keys, secrets, or `.env` file to version control!**

### Setup Instructions

1. **Create your local `.env` file:**
   ```bash
   cp .env.example .env
   ```

2. **Add your actual credentials to `.env` (locally only):**
   ```bash
   # Edit .env with your real API keys
   # This file is in .gitignore and will NOT be committed
   ```

3. **Verify `.env` is ignored:**
   ```bash
   git check-ignore .env  # Should return .env
   ```

### Getting Your API Keys

#### Firi API Keys
1. Go to [Firi Account Settings](https://firi.com/account/settings)
2. Navigate to API Keys section
3. Create a new API key pair
4. Copy `FIRI_API_KEY`, `FIRI_SECRET_KEY`, and `FIRI_CLIENT_ID`
5. Add them to your local `.env` file

#### Anthropic (Claude) API Key
1. Go to [Anthropic Console](https://console.anthropic.com)
2. Create an API key
3. Copy it to your local `.env` as `ANTHROPIC_API_KEY`

### If You Accidentally Expose a Key

**🚨 ACT IMMEDIATELY:**

1. **REVOKE the exposed key immediately** in your Firi/Anthropic account
2. **Create new keys** with rotation
3. **Update your `.env`** with the new credentials
4. If the key was committed to git history:
   ```bash
   # Rewrite git history to remove the key (DANGEROUS - only if you own repo)
   git filter-branch --force --index-filter \
     'git rm -r --cached --ignore-unmatch openai.ipynb' \
     --prune-empty --tag-name-filter cat -- --all
   
   # Force push (only do this if necessary)
   git push --force --all
   ```

### Best Practices

✅ **DO:**
- Use `.env` files for all secrets
- Add `.env` to `.gitignore` (already done in this repo)
- Rotate API keys regularly
- Use environment-specific keys (dev/prod)
- Keep secrets out of logs and error messages
- Review git history before going public

❌ **DON'T:**
- Hardcode API keys in source files
- Commit `.env` files
- Share your API keys in messages/chat/Slack
- Use the same keys across environments
- Log sensitive data
- Leave example files with real keys

### Checking for Leaks

```bash
# Search your repo for common secret patterns
grep -r "api_key\s*=" . --exclude-dir=.git
grep -r "sk-proj-" . --exclude-dir=.git
grep -r "secret_key" . --exclude-dir=.git

# Check git history
git log -p | grep "sk-proj-\|api_key ="
```

### GitHub Security Features

If your repo goes public:
1. Enable [GitHub Secret Scanning](https://docs.github.com/en/code-security/secret-scanning)
2. Set up branch protection rules
3. Require PR reviews before merge
4. Use [GitHub Actions](https://github.com/features/actions) to lint secrets

### Questions?

See the main [README.md](README.md) for more information about setup and usage.
