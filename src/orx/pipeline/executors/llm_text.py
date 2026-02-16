"""LLM text generation node executor."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import structlog

from orx.executors.base import LogPaths
from orx.pipeline.definition import NodeDefinition
from orx.pipeline.executors.base import ExecutionContext, NodeResult

logger = structlog.get_logger()


class LLMTextNodeExecutor:
    """Executor for LLM text generation nodes.

    Renders a prompt template with context and calls the LLM
    to generate text output (e.g., plan, spec, review).
    """

    def execute(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
    ) -> NodeResult:
        """Execute text generation node.

        Args:
            node: Node definition.
            context: Input context dictionary.
            exec_ctx: Execution context.

        Returns:
            NodeResult with generated text.
        """
        log = logger.bind(node_id=node.id, node_type=node.type.value)
        log.info("Executing LLM text node")

        if not node.template:
            return NodeResult(success=False, error=f"Node {node.id} has no template")

        try:
            # Render prompt
            prompt_path = self._render_prompt(node, context, exec_ctx)

            # Get log paths
            stdout_path, stderr_path = exec_ctx.paths.agent_log_paths(node.id)
            logs = LogPaths(stdout=stdout_path, stderr=stderr_path)

            # Output path for generated content
            out_path = exec_ctx.paths.context_dir / f"{node.id}_output.md"

            # Get timeout
            timeout = node.config.timeout_seconds or exec_ctx.timeout_seconds

            corr_ids = None
            started = time.perf_counter()
            if exec_ctx.observability:
                corr_ids = exec_ctx.observability.llm_request(
                    stage=node.id,
                    prompt_path=prompt_path,
                    model=exec_ctx.model_selector.model
                    if exec_ctx.model_selector
                    else None,
                    executor=exec_ctx.executor.name,
                )

            # Call LLM
            result = exec_ctx.executor.run_text(
                cwd=exec_ctx.workspace.worktree_path,
                prompt_path=prompt_path,
                out_path=out_path,
                logs=logs,
                timeout=timeout,
                model_selector=exec_ctx.model_selector,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            if exec_ctx.observability:
                exec_ctx.observability.llm_response(
                    stage=node.id,
                    result=result,
                    out_path=out_path,
                    correlation_ids=corr_ids,
                    duration_ms=duration_ms,
                )

            if result.failed:
                log.error("LLM execution failed", error=result.error_message)
                return NodeResult(
                    success=False, error=f"LLM failed: {result.error_message}"
                )

            # Read output
            if not out_path.exists():
                return NodeResult(success=False, error="LLM produced no output")

            content = out_path.read_text()

            # Build outputs
            outputs: dict[str, Any] = {}
            metadata: dict[str, Any] = {}

            if node.outputs:
                output_key = node.outputs[0]

                # Handle backlog specially
                if output_key == "backlog":
                    from orx.context.backlog import Backlog

                    backlog = Backlog.from_yaml(content)
                    outputs[output_key] = backlog
                # Handle review specially - extract verdict
                elif output_key == "review":
                    outputs[output_key] = content
                    # Parse verdict from review content
                    if "CHANGES_REQUESTED" in content:
                        metadata["verdict"] = "changes_requested"
                        metadata["feedback"] = content
                    else:
                        metadata["verdict"] = "approved"
                else:
                    outputs[output_key] = content

            log.info(
                "LLM text node completed",
                output_keys=list(outputs.keys()),
                metadata_keys=list(metadata.keys()),
            )
            return NodeResult(success=True, outputs=outputs, metadata=metadata)

        except Exception as e:
            log.error("Node execution failed", error=str(e))
            return NodeResult(success=False, error=str(e))

    def _render_prompt(
        self,
        node: NodeDefinition,
        context: dict[str, Any],
        exec_ctx: ExecutionContext,
    ) -> Path:
        """Render the prompt template.

        When context caching is enabled in the config, the static context
        (agents_context, architecture, repo_context, etc.) is rendered to
        a separate ``<stage>_system.md`` file.  Executors pick this up
        transparently for provider-side prompt caching.

        Args:
            node: Node definition.
            context: Template context.
            exec_ctx: Execution context.

        Returns:
            Path to rendered prompt file.
        """
        if node.template is None:
            msg = f"Node {node.id} has no template"
            raise ValueError(msg)

        # Map context keys to template variables and enrich from store
        template_context = self._build_template_context(context, exec_ctx)
        template_name = node.template.removesuffix(".md")

        # Render to prompts directory (with or without context split)
        caching_enabled = exec_ctx.config.context_caching.enabled
        if caching_enabled:
            exec_ctx.renderer.render_with_context_split(
                template_name,
                exec_ctx.paths.prompts_dir,
                **template_context,
            )
            # render_with_context_split already writes the files
        else:
            prompt_path = exec_ctx.paths.prompt_path(template_name)
            exec_ctx.renderer.render_to_file(
                template_name,
                prompt_path,
                **template_context,
            )

        # Copy to worktree for sandboxed executors
        # (also copies <stage>_system.md when present)
        worktree_prompt = exec_ctx.paths.copy_prompt_to_worktree(template_name)

        return worktree_prompt

    def _build_template_context(
        self, context: dict[str, Any], exec_ctx: ExecutionContext
    ) -> dict[str, Any]:
        """Build template context from input context.

        Maps artifact keys to template variable names and enriches
        with artifacts from store if missing in provided context.

        Args:
            context: Input context dictionary.
            exec_ctx: Execution context (provides artifact store).

        Returns:
            Template variable dictionary.
        """
        # Direct mappings
        template_ctx: dict[str, Any] = {}

        # Map known keys
        key_mappings = {
            "task": "task",
            "plan": "plan",
            "spec": "spec",
            "repo_map": "project_context",
            "agents_context": "agents_context",
            "architecture": "architecture_overview",
            "tooling_snapshot": "repo_context",
            "verify_commands": "verify_commands",
            "patch_diff": "patch_diff",
            "backlog": "backlog",
            "review": "review",
        }

        for ctx_key, tmpl_key in key_mappings.items():
            if ctx_key in context:
                template_ctx[tmpl_key] = context[ctx_key]
            elif exec_ctx.store.exists(ctx_key):
                # If missing from provided context, fetch from artifact store
                template_ctx[tmpl_key] = exec_ctx.store.get(ctx_key)

        # Run identity is required by some templates (e.g. decompose -> backlog.yaml).
        if "run_id" not in template_ctx:
            template_ctx["run_id"] = exec_ctx.paths.run_id
        if "max_items" not in template_ctx:
            template_ctx["max_items"] = exec_ctx.config.run.max_backlog_items

        # Pass through any additional context
        for key, value in context.items():
            if key not in key_mappings:
                template_ctx[key] = value

        return template_ctx
