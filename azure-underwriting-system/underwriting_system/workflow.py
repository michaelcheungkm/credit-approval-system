from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

from .config import AzureOpenAIConfig
from .policies import PolicyStore, create_policy_store
from .state import UnderwritingState
from .agents import (
    asset_analyst_node,
    collateral_analyst_node,
    credit_analyst_node,
    decision_agent_node,
    income_analyst_node,
    initialize_application_node,
    should_continue,
    supervisor_node,
)


class UnderwritingWorkflow:
    def __init__(self, *, llm: AzureChatOpenAI, policy_store: PolicyStore):
        self.llm = llm
        self.policy_store = policy_store
        self.graph = self._build()

    def _build(self):
        workflow = StateGraph(state_schema=UnderwritingState)

        workflow.add_node("initialize", initialize_application_node)
        workflow.add_node("supervisor", supervisor_node)

        # Bind LLM + policy store via closures
        workflow.add_node("credit", lambda s: credit_analyst_node(s, llm=self.llm, policy_store=self.policy_store))
        workflow.add_node("income", lambda s: income_analyst_node(s, llm=self.llm, policy_store=self.policy_store))
        workflow.add_node("asset", lambda s: asset_analyst_node(s, llm=self.llm, policy_store=self.policy_store))
        workflow.add_node("collateral", lambda s: collateral_analyst_node(s, llm=self.llm, policy_store=self.policy_store))
        workflow.add_node("decision", lambda s: decision_agent_node(s, llm=self.llm, policy_store=self.policy_store))

        workflow.set_entry_point("initialize")
        workflow.add_edge("initialize", "supervisor")

        workflow.add_conditional_edges(
            "supervisor",
            should_continue,
            {
                "credit": "credit",
                "income": "income",
                "asset": "asset",
                "collateral": "collateral",
                "decision": "decision",
            },
        )

        workflow.add_edge("credit", "supervisor")
        workflow.add_edge("income", "supervisor")
        workflow.add_edge("asset", "supervisor")
        workflow.add_edge("collateral", "supervisor")
        workflow.add_edge("decision", END)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    def run(self, *, case_id: str, applicant_data: dict, thread_id: str | None = None) -> UnderwritingState:
        config = {"configurable": {"thread_id": thread_id or case_id}}
        inputs: UnderwritingState = {"case_id": case_id, "applicant_data": applicant_data}

        # Run to completion
        for _ in self.graph.stream(inputs, config):
            pass

        state = self.graph.get_state(config)
        return state.values  # type: ignore[return-value]


def build_workflow(*, cfg: AzureOpenAIConfig, policies_pdf_path: str) -> UnderwritingWorkflow:
    # Some Azure chat deployments reject temperature=0; use at least 1.0.
    temperature = cfg.temperature if cfg.temperature and cfg.temperature >= 1 else 1.0
    llm = AzureChatOpenAI(
        azure_endpoint=cfg.azure_endpoint,
        api_version=cfg.api_version,
        api_key=cfg.api_key,
        azure_deployment=cfg.chat_deployment,
        temperature=temperature,
    )

    embeddings = None
    if cfg.embeddings_deployment:
        # Embeddings are optional. If the deployment name is wrong (DeploymentNotFound),
        # fall back to keyword-based policy retrieval instead of hard-failing startup.
        try:
            test_embeddings = AzureOpenAIEmbeddings(
                azure_endpoint=cfg.azure_endpoint,
                api_version=cfg.api_version,
                api_key=cfg.api_key,
                azure_deployment=cfg.embeddings_deployment,
            )
            # Validate the deployment exists.
            _ = test_embeddings.embed_query("ping")
            embeddings = test_embeddings
        except Exception:
            embeddings = None

    store = create_policy_store(
        pdf_path=policies_pdf_path,
        embeddings=embeddings,
        persist_dir=cfg.chroma_persist_dir,
    )

    return UnderwritingWorkflow(llm=llm, policy_store=store)

