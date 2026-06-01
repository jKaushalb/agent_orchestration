import json
from litellm import completion
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from agent import BaseAgent, CreateAgent, UserQuery, Query
from tools import TOOL_REGISTRY, TOOLS_to_FUNCTION
from utils import encode_image
import time
load_dotenv() 

def single_llm_call(agent, max_try=1, response_format=None):
    for j in range(max_try):
        
        if len(agent.config.tools)>0:
            agent.set_tools_definations( [TOOL_REGISTRY[k] for k in agent.config.tools] )
        response = agent.run(completion, response_format)
        output = response.choices[0].message
        if output.tool_calls:
            # print(output.tool_calls)
            tool_call = output.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            # print(function_args)

            function_response = TOOLS_to_FUNCTION[function_name](
                ** function_args
            )
            
            
            agent.add_tool_response(
                id =  tool_call.id,
                function_name = function_name,
                response = function_response,
            )

            

        else:
            return output.content
    
    
    return json.dumps({"status":"failure", "reason":"max try reached"})



# writer_system_prompt = """
# You are an excellent writer. You will write sensational article on a given topic.Write a in depth and engaging article. 
# You may be provided with a review. Fix those flaws and write and write the final article.
# """
# config = CreateAgent(name="Writer_Agent", 
#                      model_name="gemini/gemini-3.1-flash-lite", 
#                      system_prompt=writer_system_prompt, 
#                      max_output_tokens= 32200,
#                      tools=[ "wikipedia_extract", "web_search2","write_tool"]
#                     )
# Writer_Agent = BaseAgent(config)


# critic_system_prompt = """
# You are an excellent article Reviewr. Your task is to review the article and provide meticulous feedback. Think of the reader's perspective and provide the useful crticism and areas of improvements.
# Once everythin looks perfect output approved in the response and  write the article to the disk.
# """
# config = CreateAgent(name="Critic_Agent", 
#                      model_name="gemini/gemini-3.1-flash-lite", 
#                      system_prompt=critic_system_prompt,
#                      max_output_tokens= 32200 ,
#                      tools=[ "write_tool"]
#                     )
# Critic_Agent = BaseAgent(config)

# DAG = [Writer_Agent, Critic_Agent]
# max_itteration = 2
# iteration = 0

# q = "Write an article about pros and cons of AI."




        

# session_history = []
# while True and iteration<max_itteration:

    
#     if iteration==0:
#         Writer_Agent.add_message(
#                 "user",
#                 UserQuery(
#                     query= q,
#                     query_type= Query("text")
#                 )
#             )
        
#         writer_output = single_llm_call(Writer_Agent, 2)
#     else:

#         Writer_Agent.add_message(
#             "user",
#             query=UserQuery(
#                 query= f"{Critic_Agent.config.name}'s output: {critic_output}",
#                 query_type= Query("text")
#                 )
#             )
#         writer_output = single_llm_call(Writer_Agent, 2)

#     session_history.append(writer_output)
#     Critic_Agent.add_message(
#         role = "user",
#         query = UserQuery(
#             query = f"{Writer_Agent.config.name}'s output: {writer_output}" , 
#             query_type= Query("text")
#         ) 
        
#     )

#     critic_output = single_llm_call(Critic_Agent)
#     session_history.append(critic_output)

#     if "approved" in critic_output.lower():
#         break

#     iteration += 1

# print(session_history)

# print(Writer_Agent.costs)
# print(Critic_Agent.costs)




judge_prompt = """You are a Jhon cena in the field of document field's extraction. You will be given agnet's reponses and image, your task is to give them critical feedback in finalising the final field values.You will have to convince the sub agents for the correct field value.
if you feel both are wrong then make them follow your orders like Jhon cena.
once the results are finalised output the final field values through a write tool call. 
"""

first_agent_prompt = """You are an ocr agent prompt, which is humble and honest.Extract the required field's with it's correct value from the given image.
"""

second_agent_prompt = """You are a ocr specialist. Think like Tony stark and extract all the user defined fields from the given image.
"""

class PassportFields(BaseModel):
    thinking:str = Field(description="model's thinking before extracting the field values")
    key:str = Field(description="key of the field like pan no, name etc ")
    value:str = Field(description="value of the field like actual name presnt in the image etc.")

class Result(BaseModel):
    overall_thinking:str 
    data:list[PassportFields]

class JResult(Result):
    feedback:list[str] = Field(description="feedback for the agents.")


judge_config = CreateAgent(
    name = "judge_agent",
    model_name = "gemini/gemini-3.5-flash",
    system_prompt = judge_prompt,
    max_output_tokens = 40000,
    # tools = ["write_tool"]
)

judge_agent = BaseAgent(judge_config)

config = CreateAgent(name="agent1", 
                     model_name="gemini/gemini-3.1-flash-lite", 
                     system_prompt=first_agent_prompt, 
                     max_output_tokens= 32200,
                     
                    )
agent1 = BaseAgent(config)


config = CreateAgent(name="agent2", 
                     model_name="gemini/gemini-3.1-flash-lite", 
                     system_prompt=second_agent_prompt, 
                     max_output_tokens= 32200,
                    )
agent2 = BaseAgent(config)


image = encode_image("passport.jpg")


q = """
Extract the name, surname, father or husband's name, place of birth, passport type, date of birth, address, passport number, date of issue, date of expiry and mrz lines from the given image.
"""
        
iteration = 0
max_iteration=2
session_history = []

while True and iteration<max_iteration:
    if iteration==0:
        agent1.add_message(
            "user",
            query = UserQuery(
                query = [q, image],
                query_type = [Query("text"), Query("image_url")]
            )
        )
        agent1_op = single_llm_call(agent1, 2, response_format=Result)

        agent1.add_message(
            "assistant",
            query= UserQuery(
                query = agent1_op,
                query_type =  Query("text")
            )
        )

        agent2.add_message(
            "user",
            query = UserQuery(
                query = [q, image],
                query_type = [Query("text"), Query("image_url")]
            )
        )
        agent2_op = single_llm_call(agent2, 2, response_format=Result )

        agent2.add_message(
            "assistant",
            query= UserQuery(
                query = agent1_op,
                query_type =  Query("text")
            )
        )
        judge_agent.add_message(
            "user",
            
            query = UserQuery(
                query =  [q, image, f"{agent1.config.name}: agent1_op", f"{agent2.config.name}: agent2_op"],
                query_type = [Query("text"), Query("image_url"), Query("text"), Query("text")]
            )
        )
        judge_op = single_llm_call(judge_agent, 2, response_format=JResult)

        judge_agent.add_message(
            "assistant",
            query= UserQuery(
                query = judge_op,
                query_type =  Query("text")
            )
        )

        session_history.append(agent1_op)
        session_history.append(agent2_op)
        session_history.append(agent2_op)
        iteration += 1
        continue

    agent1.add_message(
            "user",
            query = UserQuery(
                query = [judge_op],
                query_type = [Query("text")]
            )
        )
    agent1_op = single_llm_call(agent1, 2, response_format=Result)

    agent1.add_message(
            "assistant",
            query= UserQuery(
                query = agent1_op,
                query_type =  Query("text")
            )
        )

    agent2.add_message(
            "user",
            query = UserQuery(
                query = [judge_op],
                query_type = [Query("text")]
            )
        )
    agent2_op = single_llm_call(agent2, 2, response_format=Result)
    agent2.add_message(
            "assistant",
            query= UserQuery(
                query = agent1_op,
                query_type =  Query("text")
            )
        )

    judge_agent.add_message(
            "user",
            query = UserQuery(
                 query =  [f"{agent1.config.name}: agent1_op", f"{agent2.config.name}: agent2_op"],
                query_type = [Query("text"), Query("text")]
      
            )
        )
    judge_op = single_llm_call(judge_agent, 3, response_format=JResult)
    judge_agent.add_message(
            "assistant",
            query= UserQuery(
                query = judge_op,
                query_type =  Query("text")
            )
        )
    session_history.append(agent1_op)
    session_history.append(agent2_op)
    session_history.append(agent2_op)
    print(session_history)
    time.sleep(30)
    iteration += 1

print(session_history)
import pickle
pickle.dump(session_history, open("../op/session_history_1.pkl", "wb"))
pickle.dump(agent1.history, open("../op/agent1_history_1.pkl", "wb"))
pickle.dump(agent2.history, open("../op/agent2_history_1.pkl", "wb"))
pickle.dump(judge_agent.history, open("../op/judge_history_1.pkl", "wb"))


print(judge_agent.costs)
print(agent1.costs)
print(agent2.costs)
        