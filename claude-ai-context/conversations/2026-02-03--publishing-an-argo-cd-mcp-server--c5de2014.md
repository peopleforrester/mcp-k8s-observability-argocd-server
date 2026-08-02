# Publishing an Argo CD MCP server

- **UUID:** c5de2014-54b1-4d77-9eae-7cdd5b293f98
- **Created:** 2026-02-03T02:19:33.621523Z
- **Updated:** 2026-02-03T02:20:25.921147Z
- **Messages:** 2

## Summary

**Conversation Overview**

The user requested help writing an informal blog post about their newly published ArgoCD MCP server. They wanted to highlight what makes their implementation different from existing MCP servers, particularly the official argoproj-labs version, emphasizing that they followed best practices to create a single-task, simple, and focused server. Claude created a conversational blog post that positioned the server as a solution to the problem of insufficient guardrails in most MCP servers, which treat all operations with the same friction level regardless of their potential impact.

The blog post highlighted seven key differentiators: dry-run by default for all write operations, three-tier permission system instead of binary read/write, configurable rate limiting to prevent API hammering, comprehensive audit logging with correlation IDs, secret masking enabled by default, optional single-cluster restriction mode, and agent-friendly error messages with actionable guidance. The user emphasized wanting real guardrails for production environments, particularly around destructive operations that require explicit confirmation parameters. The tone was deliberately informal and direct, focusing on practical "why this matters" explanations rather than just feature lists, with the core philosophy that production systems deserve more friction than development environments to prevent incidents caused by AI agents or tired operators.

**Tool Knowledge**

Claude used the create_file tool to generate the blog post as a markdown file, then used bash_tool to copy it to the outputs directory, and finally used present_files to deliver the completed work. The file was created with a descriptive filename "argocd-mcp-server-announcement-blog.md" and structured as a complete blog post with headers, code examples, configuration tables, and a conversational narrative flow that matched the user's requested informal tone while maintaining technical credibility.

## Michael — 2026-02-03T02:19:34.855645Z

I'm wanting to write a blog post about the MCP server that I created, and it's the Argo CD MCP server. Can you give me a quick blog post, kind of informal, about "Hey, I just published an MCP server. Here's what I really love about it that's different from other MCP servers, particularly around Argo"? I thought I would follow some best practices this time and see if I could create a relatively single-task, simple, focused Argo CD server. They had the following qualities that are different from other servers that I see out there.

> 📎 Attachment: txt (11103 bytes) — extracted content preserved in JSON

> 🖼️ File upload: a4dc4ad4-7c21-4f7f-b059-bf1c511f6b48 (binary content not included in export)

## Claude — 2026-02-03T02:20:25.921147Z

I'll write you an informal blog post about your ArgoCD MCP server. Let me create that MD file.

Here's your blog post. Kept it conversational—leads with the problem (most MCP servers treat all operations the same), walks through each differentiator with enough detail to be credible, and ends on the core philosophy: production deserves friction.

One thing you might want to add: the actual repo link and any installation instructions. I left a placeholder ending since I don't know where you're hosting it.
