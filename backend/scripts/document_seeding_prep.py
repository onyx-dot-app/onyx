# This script preps the documents used for initially seeding the index. It handles the embedding so that the
# documents can be added to the index with minimal processing.
import json

from pydantic import BaseModel
from sentence_transformers import SentenceTransformer  # type: ignore


class SeedPresaveDocument(BaseModel):
    url: str
    title: str
    content: str
    title_embedding: list[float]
    content_embedding: list[float]
    chunk_ind: int = 0


# Be sure to use the default embedding model
model = SentenceTransformer("nomic-ai/nomic-embed-text-v1", trust_remote_code=True)
tokenizer = model.tokenizer

# This is easier than cleaning up the crawl, needs to be updated if the sites are changed
overview_title = "Use Cases Overview"
overview = (
    "How to leverage Onyx in your organization\n\n"
    "Onyx Overview\n"
    "Onyx is the AI Assistant connected to your organization's docs, apps, and people. "
    "Onyx makes Generative AI more versatile for work by enabling new types of questions like "
    '"What is the most common feature request we\'ve heard from customers this month". '
    "Whereas other AI systems have no context of your team and are generally unhelpful with work related questions, "
    "Onyx makes it possible to ask these questions in natural language and get back answers in seconds.\n\n"
    "Onyx can connect to +30 different tools and the use cases are not limited to the ones in the following pages. "
    "The highlighted use cases are for inspiration and come from feedback gathered from our users and customers.\n\n\n"
    "Common Getting Started Questions:\n\n"
    "Why are these docs connected in my Onyx deployment?\n"
    "Answer: This is just an example of how connectors work in Onyx. You can connect up your own team's knowledge "
    "and you will be able to ask questions unique to your organization. Onyx will keep all of the knowledge up to date "
    "and in sync with your connected applications.\n\n"
    "Is my data being sent anywhere when I connect it up to Onyx?\n"
    "Answer: No! Onyx is built with data security as our highest priority. We open sourced it so our users can know "
    "exactly what is going on with their data. By default all of the document processing happens within Onyx. "
    "The only time it is sent outward is for the GenAI call to generate answers.\n\n"
    "Where is the feature for auto sync-ing document level access permissions from all connected sources?\n"
    "Answer: This falls under the Enterprise Edition set of Onyx features built on top of the MIT/community edition. "
    "If you are on Onyx Cloud, you have access to them by default. If you're running it yourself, reach out to the "
    "Onyx team to receive access."
)

enterprise_search_title = "Enterprise Search"
enterprise_search_1 = (
    "Value of Enterprise Search with Onyx\n\n"
    "What is Enterprise Search and why is it Important?\n"
    "An Enterprise Search system gives team members a single place to access all of the disparate knowledge "
    "of an organization. Critical information is saved across a host of channels like call transcripts with "
    "prospects, engineering design docs, IT runbooks, customer support email exchanges, project management "
    "tickets, and more. As fast moving teams scale up, information gets spread out and more disorganized.\n\n"
    "Since it quickly becomes infeasible to check across every source, decisions get made on incomplete "
    "information, employee satisfaction decreases, and the most valuable members of your team are tied up "
    "with constant distractions as junior teammates are unable to unblock themselves. Onyx solves this "
    "problem by letting anyone on the team access all of the knowledge across your organization in a "
    "permissioned and secure way. Users can ask questions in natural language and get back answers and "
    "documents across all of the connected sources instantly.\n\n"
    "What's the real cost?\n"
    "A typical knowledge worker spends over 2 hours a week on search, but more than that, the cost of "
    "incomplete or incorrect information can be extremely high. Customer support/success that isn't able "
    "to find the reference to similar cases could cause hours or even days of delay leading to lower "
    "customer satisfaction or in the worst case - churn. An account exec not realizing that a prospect had "
    "previously mentioned a specific need could lead to lost deals. An engineer not realizing a similar "
    "feature had previously been built could result in weeks of wasted development time and tech debt with "
    "duplicate implementation. With a lack of knowledge, your whole organization is navigating in the dark "
    "- inefficient and mistake prone."
)

enterprise_search_2 = (
    "More than Search\n"
    "When analyzing the entire corpus of knowledge within your company is as easy as asking a question "
    "in a search bar, your entire team can stay informed and up to date. Onyx also makes it trivial "
    "to identify where knowledge is well documented and where it is lacking. Team members who are centers "
    "of knowledge can begin to effectively document their expertise since it is no longer being thrown into "
    "a black hole. All of this allows the organization to achieve higher efficiency and drive business outcomes.\n\n"
    "With Generative AI, the entire user experience has evolved as well. For example, instead of just finding similar "
    "cases for your customer support team to reference, Onyx breaks down the issue and explains it so that even "
    "the most junior members can understand it. This in turn lets them give the most holistic and technically accurate "
    "response possible to your customers. On the other end, even the super stars of your sales team will not be able "
    "to review 10 hours of transcripts before hopping on that critical call, but Onyx can easily parse through it "
    "in mere seconds and give crucial context to help your team close."
)

ai_platform_title = "AI Platform"
ai_platform = (
    "Build AI Agents powered by the knowledge and workflows specific to your organization.\n\n"
    "Beyond Answers\n"
    "Agents enabled by generative AI and reasoning capable models are helping teams to automate their work. "
    "Onyx is helping teams make it happen. Onyx provides out of the box user chat sessions, attaching custom tools, "
    "handling LLM reasoning, code execution, data analysis, referencing internal knowledge, and much more.\n\n"
    "Onyx as a platform is not a no-code agent builder. We are made by developers for developers and this gives your "
    "team the full flexibility and power to create agents not constrained by blocks and simple logic paths.\n\n"
    "Flexibility and Extensibility\n"
    "Onyx is open source and completely whitebox. This not only gives transparency to what happens within the system "
    "but also means that your team can directly modify the source code to suit your unique needs."
)

customer_support_title = "Customer Support"
customer_support = (
    "Help your customer support team instantly answer any question across your entire product.\n\n"
    "AI Enabled Support\n"
    "Customer support agents have one of the highest breadth jobs. They field requests that cover the entire surface "
    "area of the product and need to help your users find success on extremely short timelines. "
    "Because they're not the same people who designed or built the system, they often lack the depth of understanding "
    "needed - resulting in delays and escalations to other teams. Modern teams are leveraging AI to help their CS team "
    "optimize the speed and quality of these critical customer-facing interactions.\n\n"
    "The Importance of Context\n"
    "There are two critical components of AI copilots for customer support. The first is that the AI system needs to be "
    "connected with as much information as possible (not just support tools like Zendesk or Intercom) and that the "
    "knowledge needs to be as fresh as possible. Sometimes a fix might even be in places rarely checked by CS such as "
    "pull requests in a code repository. The second critical component is the ability of the AI system to break down "
    "difficult concepts and convoluted processes into more digestible descriptions and for your team members to be able "
    "to chat back and forth with the system to build a better understanding.\n\n"
    "Onyx takes care of both of these. The system connects up to over 30+ different applications and the knowledge is "
    "pulled in constantly so that the information access is always up to date."
)

sales_title = "Sales"
sales = (
    "Keep your team up to date on every conversation and update so they can close.\n\n"
    "Recall Every Detail\n"
    "Being able to instantly revisit every detail of any call without reading transcripts is helping Sales teams provide "
    "more tailored pitches, build stronger relationships, and close more deals. Instead of searching and reading through "
    'hours of transcripts in preparation for a call, your team can now ask Onyx "What specific features was ACME '
    "interested in seeing for the demo\". Since your team doesn't have time to read every transcript prior to a call, "
    "Onyx provides a more thorough summary because it can instantly parse hundreds of pages and distill out the relevant "
    "information. Even for fast lookups it becomes much more convenient - for example to brush up on connection building "
    'topics by asking "What rapport building topic did we chat about in the last call with ACME".\n\n'
    "Know Every Product Update\n"
    "It is impossible for Sales teams to keep up with every product update. Because of this, when a prospect has a question "
    "that the Sales team does not know, they have no choice but to rely on the Product and Engineering orgs to get an "
    "authoritative answer. Not only is this distracting to the other teams, it also slows down the time to respond to the "
    "prospect (and as we know, time is the biggest killer of deals). With Onyx, it is even possible to get answers live "
    'on call because of how fast accessing information becomes. A question like "Have we shipped the Microsoft AD '
    'integration yet?" can now be answered in seconds meaning that prospects can get answers while on the call instead of '
    "asynchronously and sales cycles are reduced as a result."
)

operations_title = "Operations"
operations = (
    "Double the productivity of your Ops teams like IT, HR, etc.\n\n"
    "Automatically Resolve Tickets\n"
    "Modern teams are leveraging AI to auto-resolve up to 50% of tickets. Whether it is an employee asking about benefits "
    "details or how to set up the VPN for remote work, Onyx can help your team help themselves. This frees up your team to "
    "do the real impactful work of landing star candidates or improving your internal processes.\n\n"
    "AI Aided Onboarding\n"
    "One of the periods where your team needs the most help is when they're just ramping up. Instead of feeling lost in dozens "
    "of new tools, Onyx gives them a single place where they can ask about anything in natural language. Whether it's how to "
    "set up their work environment or what their onboarding goals are, Onyx can walk them through every step with the help "
    "of Generative AI. This lets your team feel more empowered and gives time back to the more seasoned members of your team to "
    "focus on moving the needle."
)

# For simplicity, we're not adding any metadata suffix here. Generally there is none for the Web connector anyway
overview_doc = SeedPresaveDocument(
    url="https://docs.onyx.app/more/use_cases/overview",
    title=overview_title,
    content=overview,
    title_embedding=list(model.encode(f"search_document: {overview_title}")),
    content_embedding=list(
        model.encode(f"search_document: {overview_title}\n{overview}")
    ),
)

enterprise_search_doc = SeedPresaveDocument(
    url="https://docs.onyx.app/more/use_cases/enterprise_search",
    title=enterprise_search_title,
    content=enterprise_search_1,
    title_embedding=list(model.encode(f"search_document: {enterprise_search_title}")),
    content_embedding=list(
        model.encode(
            f"search_document: {enterprise_search_title}\n{enterprise_search_1}"
        )
    ),
)

enterprise_search_doc_2 = SeedPresaveDocument(
    url="https://docs.onyx.app/more/use_cases/enterprise_search",
    title=enterprise_search_title,
    content=enterprise_search_2,
    title_embedding=list(model.encode(f"search_document: {enterprise_search_title}")),
    content_embedding=list(
        model.encode(
            f"search_document: {enterprise_search_title}\n{enterprise_search_2}"
        )
    ),
    chunk_ind=1,
)

ai_platform_doc = SeedPresaveDocument(
    url="https://docs.onyx.app/more/use_cases/ai_platform",
    title=ai_platform_title,
    content=ai_platform,
    title_embedding=list(model.encode(f"search_document: {ai_platform_title}")),
    content_embedding=list(
        model.encode(f"search_document: {ai_platform_title}\n{ai_platform}")
    ),
)

customer_support_doc = SeedPresaveDocument(
    url="https://docs.onyx.app/more/use_cases/support",
    title=customer_support_title,
    content=customer_support,
    title_embedding=list(model.encode(f"search_document: {customer_support_title}")),
    content_embedding=list(
        model.encode(f"search_document: {customer_support_title}\n{customer_support}")
    ),
)

sales_doc = SeedPresaveDocument(
    url="https://docs.onyx.app/more/use_cases/sales",
    title=sales_title,
    content=sales,
    title_embedding=list(model.encode(f"search_document: {sales_title}")),
    content_embedding=list(model.encode(f"search_document: {sales_title}\n{sales}")),
)

operations_doc = SeedPresaveDocument(
    url="https://docs.onyx.app/more/use_cases/operations",
    title=operations_title,
    content=operations,
    title_embedding=list(model.encode(f"search_document: {operations_title}")),
    content_embedding=list(
        model.encode(f"search_document: {operations_title}\n{operations}")
    ),
)

documents = [
    overview_doc,
    enterprise_search_doc,
    enterprise_search_doc_2,
    ai_platform_doc,
    customer_support_doc,
    sales_doc,
    operations_doc,
]

documents_dict = [doc.model_dump() for doc in documents]

with open("./backend/onyx/seeding/initial_docs.json", "w") as json_file:
    json.dump(documents_dict, json_file, indent=4)
