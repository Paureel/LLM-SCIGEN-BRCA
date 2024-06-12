import streamlit as st
import os
import datetime
import pandas as pd
from langchain_openai import ChatOpenAI
from langchain.vectorstores import Chroma
from langchain_core.pydantic_v1 import BaseModel, Field, ValidationError
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from langchain.tools.retriever import create_retriever_tool
from langchain.chains import ConversationalRetrievalChain
from langgraph.prebuilt import ToolExecutor, ToolNode
from langchain_core.tools import StructuredTool
from langgraph.graph import END, MessageGraph
import warnings
from langchain.embeddings.openai import OpenAIEmbeddings
from typing import Literal
from langchain_core.output_parsers import StrOutputParser


import nest_asyncio
nest_asyncio.apply()

from nemoguardrails import RailsConfig
from nemoguardrails.integrations.langchain.runnable_rails import RunnableRails
warnings.filterwarnings("ignore")

def apply_custom_css():
    """
    Apply custom CSS for better aesthetics.
    """
    st.markdown("""
        <style>
        .reportview-container {
            background: linear-gradient(to right, #6a11cb 0%, #2575fc 100%);
            color: white;
        }
        .sidebar .sidebar-content {
            background: #ffffff;
            color: black;
        }
        .css-18e3th9 {
            padding: 2rem 1rem 10rem;
        }
        .stButton button {
            background-color: #ff4b4b;
            color: white;
            border-radius: 10px;
        }
        .stTextInput, .stTextInput input {
            background-color: #ffffff;
            border-radius: 10px;
        }
        </style>
    """, unsafe_allow_html=True)


def set_environment_variables():
    """
    Set environment variables required for the application.
    """
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGCHAIN_PROJECT"] = "Reflexion"


@st.cache_resource()
def setup_chroma():
    """
    Setup Chroma database with the OpenAI embeddings model.
    
    Returns:
        Chroma: The Chroma database object.
    """
    embed_model = OpenAIEmbeddings(model="text-embedding-3-large")
    db = Chroma(persist_directory="db_pubmed_brca", embedding_function=embed_model)
    return db


class Reflection(BaseModel):
    """
    A model for reflections on the hypothesis.
    """
    missing: str = Field(description="Critique of what is missing.")
    superfluous: str = Field(description="Critique of what is superfluous")
    notnovel: str = Field(description="Critique of what has been already published")
    shortname: str = Field(description="A one sentence long summary of the core idea in the hypothesis")
    noveltyscore: str = Field(description="A number between 0 and 10 on how novel the hypothesis is")
    references_field: str = Field(description="References by pubmed id or other ids")
    flag: str = Field(description="Does the hypothesis make sense? Consider if the input gene names and other features are real, and rethink if the generated hypothesis makes sense or not.")


class AnswerQuestion(BaseModel):
    """
    A model for answering questions and providing reflections and search queries.
    """
    answer: str = Field(description="~250 word detailed answer to the question.")
    reflection: Reflection = Field(description="Your reflection on the initial answer.")
    search_queries: list[str] = Field(description="1-3 search queries for researching improvements to address the critique of your current answer.")


class ReviseAnswer(AnswerQuestion):
    """
    Revise the original answer to the question. Provide an answer, reflection, cite your reflection with references, and add search queries to improve the answer.
    """
    references: list[str] = Field(description="Citations motivating your updated answer.")


class ResponderWithRetries:
    """
    A class that handles responding with retries in case of validation errors.
    """
    def __init__(self, runnable, validator):
        self.runnable = runnable
        self.validator = validator

    def respond(self, state: list):
        """
        Attempt to respond to a given state, retrying up to 3 times in case of validation errors.
        
        Args:
            state (list): The current state of the conversation.
        
        Returns:
            response: The response generated by the runnable.
        """
        for attempt in range(3):
            response = self.runnable.invoke({"messages": state}, {"tags": [f"attempt:{attempt}"]})
            try:
                self.validator.invoke(response)
                return response
            except ValidationError as e:
                state = state + [
                    response,
                    ToolMessage(
                        content=f"{repr(e)}\n\nPay close attention to the function schema.\n\n"
                                + self.validator.schema_json()
                                + " Respond by fixing all validation errors.",
                        tool_call_id=response.tool_calls[0]["id"],
                    ),
                ]
        return response


class HypothesisGenerator:
    """
    A class to handle the generation of hypotheses using LangChain tools.
    """
    def __init__(self, api_key, agent_iterations, iterations, gene_name, disease_input, output_variable_input, known_hypotheses_input,hypothesis_type):
        self.api_key = api_key
        self.agent_iterations = agent_iterations
        self.iterations = iterations
        self.llm = ChatOpenAI(model="gpt-4o", streaming=True)
        self.llm_short = ChatOpenAI(model="gpt-4o", streaming=True)
        self.db = setup_chroma()
        self.retriever = self.db.as_retriever()
        self.retrieval_chain = ConversationalRetrievalChain.from_llm(
            llm=self.llm,
            retriever=self.retriever
        )
        self.setup_prompt_templates(gene_name, disease_input, output_variable_input, known_hypotheses_input,hypothesis_type)
        self.setup_tool_executor()
        self.setup_graph()

    def setup_tool_executor(self):
        """
        Setup the tool executor with the necessary tools.
        """
        def run_queries(search_queries: list[str], **kwargs):
            """
            Run the generated queries.
            
            Args:
                search_queries (list[str]): List of search queries to run.
            
            Returns:
                results (list): List of responses for each query.
            """
            results = []
            for query in search_queries:
                response = self.retrieval_chain({"chat_history": "", "question": query})['answer']
                results.append(response)
            return results

        retriever_tool = create_retriever_tool(
            self.retriever,
            "retrieve_papers",
            "Search and return information about publications."
        )

        self.tools = [retriever_tool]
        self.tool_executor = ToolExecutor(self.tools)

        self.tool_node = ToolNode(
            [
                StructuredTool.from_function(run_queries, name=AnswerQuestion.__name__),
                StructuredTool.from_function(run_queries, name=ReviseAnswer.__name__),
            ]
        )

    def setup_graph(self):
        """
        Setup the message graph for hypothesis generation.
        """
        self.builder = MessageGraph()
        self.builder.add_node("draft", self.first_responder.respond)
        self.builder.add_node("execute_tools", self.tool_node)
        self.builder.add_node("revise", self.revisor.respond)

        # draft -> execute_tools
        self.builder.add_edge("draft", "execute_tools")
        # execute_tools -> revise
        self.builder.add_edge("execute_tools", "revise")

        self.builder.add_conditional_edges("revise", self.event_loop)
        self.builder.set_entry_point("draft")
        self.graph = self.builder.compile()

    def generate_hypotheses(self, gene_name, disease_input, output_variable_input, known_hypotheses_input):
        """
        Generate hypotheses based on the provided inputs.
        
        Args:
            gene_name (str): Name of the gene.
            disease_input (str): Name of the disease.
            output_variable_input (str): Target variable.
            known_hypotheses_input (str): Known hypotheses to exclude.
        
        Returns:
            pd.DataFrame: DataFrame containing the generated hypotheses.
        """
        initial = self.first_responder.respond([HumanMessage(content="Come up with new hypotheses in the context.")])
        st.session_state.hypothesisdf_all = pd.DataFrame()
        notnovelhyp = ""
        for hypothesis_cycle in range(self.iterations):
            
            events = self.graph.stream(
                [HumanMessage(
                    content=f"Come up with new hypotheses in the context. ALWAYS make sure that your hypothesis is novel compared to the following known hypotheses (don't include the known hypotheses and don't generate anything related to them conceptually): {notnovelhyp}")],
                stream_mode="values",
            )
            for i, step in enumerate(events):
                st.write(step[-1])
            prompt = ChatPromptTemplate.from_messages([
    ("system", "You are world class technical documentation writer."),
    ("user", "{input}")
])
            output_parser = StrOutputParser()
            config = RailsConfig.from_path("config")
            guardrails = RunnableRails(config)

            chain = prompt | self.llm | output_parser
            chain_short = prompt | self.llm_short | output_parser


            chain_with_guardrails = guardrails | chain
            
            shortname_hyp = step[-1].tool_calls[0]["args"]["reflection"]['shortname']
            
            listofpapers = str(self.db.similarity_search(shortname_hyp))
            prompt_short = ChatPromptTemplate.from_messages([
    ("system", "You are world class technical documentation writer. Given a list of publications, decide how the following hypothesis relates to it: " + shortname_hyp),
    ("user", "The list of publications: {input}")
])
            output_parser = StrOutputParser()
            
            chain_short = prompt | self.llm_short | output_parser


            
            
            
            
            hypothesisdf = pd.DataFrame({
                "Hypotheses short description": step[-1].tool_calls[0]["args"]["reflection"]['shortname'],
                "Generated Hypotheses": step[-1].tool_calls[0]["args"]["answer"],
                "Novelty": step[-1].tool_calls[0]["args"]["reflection"]['noveltyscore'],
                "What is not novel": step[-1].tool_calls[0]["args"]["reflection"]['notnovel'],
                "Missing": step[-1].tool_calls[0]["args"]["reflection"]['missing'],
                "Superfluous": step[-1].tool_calls[0]["args"]["reflection"]['superfluous'],
                "Flag": step[-1].tool_calls[0]["args"]["reflection"]['flag'],
                "References": step[-1].tool_calls[0]["args"]["reflection"]['references_field'],
                "Biohazard": chain_with_guardrails.invoke("Does the following contain any restricted topics?: "+ (step[-1].tool_calls[0]["args"]["answer"])),
                "Relations to literature" : chain_short.invoke(listofpapers)
            }, index=[0])
            st.session_state.hypothesisdf_all = pd.concat([st.session_state.hypothesisdf_all, hypothesisdf],
                                                          ignore_index=True)
            notnovelhyp = notnovelhyp + step[-1].tool_calls[0]["args"]["reflection"]['shortname']

        return st.session_state.hypothesisdf_all

    def event_loop(self, state: list) -> Literal["execute_tools", "__end__"]:
        """
        Determine the next step in the event loop based on the number of iterations.
        
        Args:
            state (list): The current state of the conversation.
        
        Returns:
            str: The next step in the event loop.
        """
        num_iterations = self._get_num_iterations(state)
        if num_iterations > self.agent_iterations:
            return END
        return "execute_tools"

    def _get_num_iterations(self, state: list):
        """
        Get the number of iterations from the state.
        
        Args:
            state (list): The current state of the conversation.
        
        Returns:
            int: The number of iterations.
        """
        i = 0
        for m in state[::-1]:
            if m.type not in {"tool", "ai"}:
                break
            i += 1
        return i

    def setup_prompt_templates(self, gene_name, disease_input, output_variable_input, known_hypotheses_input,hypothesis_type):
        """
        Setup the prompt templates for generating hypotheses.
        
        Args:
            gene_name (str): Name of the gene.
            disease_input (str): Name of the disease.
            output_variable_input (str): Target variable.
            known_hypotheses_input (str): Known hypotheses to exclude.
        """
        example1 = "Hypothesis Name: Synthetic Lethality of PARP Inhibitors in Triple Negative Breast Cancer (TNBC) Long Description and Reasoning: Synthetic lethality occurs when the combination of mutations in two or more genes leads to cell death, whereas a mutation in only one of these genes does not. In the context of cancer therapy, this concept is exploited by targeting specific pathways altered by cancer mutations with drugs that further push cancer cells towards cell death, while sparing normal cells.Triple Negative Breast Cancer (TNBC) is characterized by the absence of estrogen receptors, progesterone receptors, and minimal HER2 expression, which limits treatment options because hormonal and HER2-targeted therapies are ineffective. TNBC is often associated with defects in DNA repair mechanisms, particularly in the BRCA1 and BRCA2 genes, which are crucial for the repair of double-strand breaks in DNA through the homologous recombination repair (HRR) pathway.PARP (poly ADP-ribose polymerase) inhibitors, such as olaparib, exploit this vulnerability. PARP is a key enzyme in the repair of single-strand breaks (SSBs) in DNA. When PARP is inhibited in cells that already have compromised HRR due to BRCA mutations (or similar defects), the accumulation of SSBs leads to double-strand breaks during DNA replication. Since these cells cannot effectively repair double-strand breaks due to the existing HRR defect, this leads to increased genomic instability and eventual cell death—a phenomenon exemplified by synthetic lethality. In-Silico and In-Vitro Validation Recommendations: In-Silico Studies: Genetic Analysis: Utilize genomic data from TNBC patients to identify potential mutations in DNA repair pathways that could predict sensitivity to PARP inhibitors. Molecular Docking and Dynamics Simulations: Perform simulations to study the interaction between PARP inhibitors and the PARP enzyme in different mutant contexts, which can help in understanding the binding efficiency and potential resistance mechanisms. Pathway Analysis: Use systems biology approaches to simulate the impact of PARP inhibition on cellular pathways, particularly focusing on DNA repair and apoptosis pathways in TNBC models. In-Vitro Studies: Cell Viability Assays: Test the cytotoxicity of PARP inhibitors on cultured TNBC cells, particularly those genetically engineered to knock out BRCA1/2 or other related genes involved in HRR. Reporter Assays: Employ reporter assays to measure the activity of DNA repair pathways upon treatment with PARP inhibitors. Combination Therapy Studies: Investigate the efficacy of PARP inhibitors in combination with other drugs (like DNA damaging agents) to explore potential synergistic effects. Gene Expression Profiling: Analyze changes in gene expression related to cell cycle regulation, DNA repair, and apoptosis following treatment with PARP inhibitors. This comprehensive approach combining in-silico predictions and in-vitro experiments can help to validate the hypothesis of synthetic lethality with PARP inhibitors in TNBC and optimize therapeutic strategies. Novelty and Complexity of the Hypothesis:The concept of using PARP inhibitors for synthetic lethality in TNBC represents a novel therapeutic approach that diverges from traditional cancer treatments which typically focus on targeting the rapid division of all actively dividing cells. This hypothesis is particularly innovative because it specifically targets the unique genetic vulnerabilities of TNBC cells, exploiting their inherent DNA repair deficiencies.Developing this hypothesis required complex, non-trivial thinking due to several reasons: Understanding the Interplay of Genetic Pathways: The hypothesis relies on a deep understanding of the cellular and molecular biology of cancer, particularly the intricate mechanisms of DNA damage and repair. Researchers needed to integrate knowledge from various studies to hypothesize that inhibiting a single-strand DNA repair enzyme could be lethal in cells already deficient in double-strand DNA repair. Integration of Genetic Diversity: TNBC is a highly heterogeneous disease with variable genetic backgrounds among patients. Identifying a common vulnerability (like defective DNA repair mechanisms) across diverse genetic profiles necessitates sophisticated analysis and interpretation of genetic data. Predicting Off-Target Effects: The hypothesis had to consider the potential effects of PARP inhibitors on normal cells, necessitating a thoughtful approach to predict and mitigate possible toxicities, thus requiring careful balance between efficacy and safety in therapeutic design. Innovative Drug Targeting: The use of PARP inhibitors in the context of synthetic lethality is a relatively recent development in oncology. Designing drugs that can selectively kill cancer cells by exploiting specific genetic deficiencies required innovative thinking and novel methodologies in both drug development and cancer treatment strategies. This hypothesis, therefore, represents a significant advancement in the targeted therapy of TNBC, offering a potential treatment option where few effective therapies currently exist. It embodies a shift towards personalized medicine and requires ongoing research and sophisticated techniques to fully realize its therapeutic potential. References: Pubmed ID 342432432, 4342332"

        system_prompt = "You are a professional hypothesis generator AI in cancer biology, who proposes new, really out-of-the-box hypotheses."
        model_prompt = f"I trained a statistical learning model. I trained the model to predict the {output_variable_input} in {disease_input} samples. The most important features (org genes) were: {gene_name}"
        task_description = f"The central question is that what causes {output_variable_input} given these and how to exploit it therapeutically in {disease_input}."
        output_prompt = "Hypothesis on a potential new" + hypothesis_type + "interaction which helps cure cancer patient for this particular cancer, when combined with the output of the model and hypotheses. Here, try to reference known drugs, or drug combination which can be used to test the hypothesis. ALWAYS try to explain why you can see the output variable effect in the input variables (for example genes), and include this in your reasoning."
        output_structure = "1. Hypothesis name, 2. Long description and reasoning, 3. In-silico and in-vitro validation recommendations. 4. Novelty and Complexity of the Hypothesis (Why is it novel and why it needed non-trivial complex thinking to come up with). Here you can see an example: " + example1
        main_prompt = system_prompt + model_prompt + task_description + "Your output should be: " + output_prompt + ", While adhering to the following output structure: " + output_structure + ". Be very strict, if the input gene names or other input features dont seem real (typo, etc), admit that you can't generate anything. Apart from these structural requirements, ALWAYS make sure that your hypothesis is novel compared to the following known hypotheses (don't include the known hypotheses and don't generate anything related to them conceptually): " + known_hypotheses_input

        actor_prompt_template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are expert researcher. """ + main_prompt + """
            Current time: {time}

            1. {first_instruction}
            2. Reflect and critique your answer. Be severe to maximize improvement.
            3. Recommend search queries to research information and improve your answer.""",
                ),
                MessagesPlaceholder(variable_name="messages"),
                (
                    "user",
                    "\n\n<system>Reflect on the user's original question and the"
                    " actions taken thus far. Respond using the {function_name} function.</reminder>",
                ),
            ]
        ).partial(
            time=lambda: datetime.datetime.now().isoformat(),
        )

        self.initial_answer_chain = actor_prompt_template.partial(
            first_instruction="Provide a detailed ~250 word answer.",
            function_name=AnswerQuestion.__name__,
        ) | self.llm.bind_tools(tools=[AnswerQuestion])
        self.validator = PydanticToolsParser(tools=[AnswerQuestion])

        self.first_responder = ResponderWithRetries(
            runnable=self.initial_answer_chain, validator=self.validator
        )
        self.revision_chain = actor_prompt_template.partial(
            first_instruction=self.revise_instructions,
            function_name=ReviseAnswer.__name__,
        ) | self.llm.bind_tools(tools=[ReviseAnswer])
        self.revision_validator = PydanticToolsParser(tools=[ReviseAnswer])

        self.revisor = ResponderWithRetries(runnable=self.revision_chain, validator=self.revision_validator)

    @property
    def revise_instructions(self):
        """
        Instructions for revising the initial answer.
        
        Returns:
            str: The instructions for revising the answer.
        """
        return """Revise your previous answer using the new information.
            - You should use the previous critique to add important information to your answer.
                - You MUST include numerical citations in your revised answer to ensure it can be verified.
                - Add a "References" section to the bottom of your answer (which does not count towards the word limit). In form of:
                    - [1] Example context or source 1
                    - [2] Example context or source 2
            - You should use the previous critique to remove superfluous information and not novel concepts from your answer and make SURE it is not more than 250 words.
        """


def main():
    """
    Main function to run the Streamlit application.
    """
    apply_custom_css()
    set_environment_variables()

    st.title("🧬 Hypothesis Generator")
    st.markdown("### Generate novel hypotheses for cancer research based on the output of statistical models")
    st.markdown('<p style="color:red;">This is an experimental tool and is prone to hallucinate a lot. Always check the generated output for biological validity! </p>', unsafe_allow_html=True)

    api_key1 = st.text_input("Enter your OpenAI API Key (will switch to fully NVIDIA API when tool calling will be enabled)", type="password")
    
    if api_key1:
        os.environ["OPENAI_API_KEY"] = api_key1
        
        
        
        gene_name = st.text_input("Enter Gene Names", value="BRCA1, BRCA2",help='You can add more information, for example BRCA1 (downregulated), BRCA2(silenced)')
        disease_input = st.text_input("Enter Disease Name (for example triple negative breast cancer)",value="triple negative breast cancer")
        output_variable_input = st.text_input("Enter Target Variable (for example HR-proficient vs HR-deficient)",value="homologous recombination-proficient vs homologous recombination-deficient")
        hypothesis_type = st.text_input("Enter the hypothesis type (for example new synthetic lethality interaction)",value="synthetic lethality interaction")

        known_hypotheses_input = st.text_input("Here you can enter previously known hypotheses to exclude")
        agent_iterations = st.slider("How many times an agent should reiterate on a given hypothesis?", min_value=1, max_value=10, value=2)
        iterations = st.slider("Number of Generated Hypotheses", min_value=1, max_value=10, value=2)

        generator = HypothesisGenerator(api_key1, agent_iterations, iterations, gene_name, disease_input, output_variable_input, known_hypotheses_input, hypothesis_type)

        if st.button("Generate Hypothesis"):
            with st.status("Generating hypotheses..."):
                hypotheses_df = generator.generate_hypotheses(gene_name, disease_input, output_variable_input, known_hypotheses_input)
            st.dataframe(hypotheses_df)
            st.session_state.hypothesisdf_all.to_csv("hypotheses_o.csv")
            st.download_button("Download Hypotheses", data=hypotheses_df.to_csv(index=False).encode('utf-8'), file_name="hypotheses.csv", mime='text/csv')


if __name__ == "__main__":
    main()
