# Scientific Hypothesis Generator in Breast Cancer research

![Project Banner](banner.png) 
## 🚀 Introduction

Welcome to **Scientific Hypothesis Generator in Breast Cancer research**! This project leverages the power of large language models to assist researchers, scientists, and enthusiasts in generating innovative scientific ideas given the output of statistical learning models in breast cancer research.

## 📚 Features

- **Hypothesis Generation**: Generate unique, and testable scientific hypothesis based on the output of statistical learning tools, representable on gene level (DeSeq2, ..).
- **Customizable Vector Database**: Tailor the vector database to fit your specific field or area of interest (tested on papers related to breast cancer research).
- **High-Quality Output**: Utilizes state-of-the-art language models to ensure high relevance and quality of generated ideas, with in-vitro and in-silico validation recommendations.
- **User-Friendly Interface**: Easy-to-use interface for seamless idea generation, using the streamlit framework.

## 🌟 Demo

Check out our [live demo](https://example.com/demo) to see the app in action!

## 🛠️ Installation

To get started, clone this repository and install the necessary dependencies:

```bash
git clone https://github.com/yourusername/scientific-idea-generator.git
cd scientific-idea-generator
pip install -r requirements.txt
```

## 🚀 Usage

1. To generate scientific ideas, simply run the following command to launch the app:

```bash
streamlit run app.py
```

2. Fill out the fields in the app. First set your NVIDIA API key. Then enter the gene names which were indicated as important or differentially expressed (you can specify the direction as well, the prompting is quite flexible, for example: *TP53* (upregulated), *BRCA1* (downregulated)). Specify the disease type (for example triple negative breast cancer). Enter the target variable, which is just basically the variable you used to fit your statistical learning model (for example: cisplatin sensitive/resistant subgroups). Again, you can be quite flexible when it comes to prompting, the model will incorporate any additional information.


## 🧩 How It Works

The model is based on the Reflexion agentic workflow by Shinn et al. https://github.com/langchain-ai/langgraph/blob/main/examples/reflexion/reflexion.ipynb. By inputting a custom prompt, the model generates a series of potential ideas or research questions that could inspire your next scientific endeavor.

## Customizations powered by Nvidia

- NeMo Guardrails
- Foundation models through the NVIDIA NIM APIs or endpoints

## IMPORTANT

The model is prone to hallucinate a lot, so always validate the generated ideas!

## 🔧 TODO

- [ ] Improve the idea generation algorithm for more diverse outputs.
- [ ] Add support for more customizable prompt options.
- [ ] Implement a feedback loop for users to rate the quality of generated ideas.
- [ ] Integrate with external databases for real-time scientific data.
- [ ] Visualize the hypotheses in embedding space.


## 🤝 Contributing

Contributions are welcome! If you'd like to contribute to this project, please fork the repository and create a pull request. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

## 🙌 Acknowledgements

- [Langchain](https://github.com/langchain-ai/langgraph/tree/main/examples/reflexion) for the Reflexion agentic workflow this model is based on. The original publication by Shinn et al. can be found here: https://arxiv.org/abs/2303.11366.
- [NVIDIA](https://build.nvidia.com/explore/discover) for providing access to the NVIDIA NIM api, used to develop this model.


## 🌐 Connect with Us

- [GitHub Issues](https://github.com/Paureel/scientific-idea-generator/issues)
- [Discussions](https://github.com/Paureel/scientific-idea-generator/discussions)
- [Twitter/X](https://x.com/aurel_pr)
- [LLM-SCI-GEN](https://github.com/Paureel/LLM-SCI-GEN) Papers about scientific hypothesis generation with large language models (LLMs), maintained by me. Check it out if you are interested in this topic.