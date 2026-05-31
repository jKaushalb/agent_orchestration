import json
from litellm import completion
from dotenv import load_dotenv

from agent import BaseAgent, CreateAgent, UserQuery, Query
from tools import TOOL_REGISTRY, TOOLS_to_FUNCTION

load_dotenv() 


writer_system_prompt = """
You are an excellent writer. You will write sensational article on a given topic.Write a in depth and engaging article. 
You may be provided with a review. Fix those flaws and write and write the final article.
"""
config = CreateAgent(name="Writer_Agent", 
                     model_name="gemini/gemini-3.1-flash-lite", 
                     system_prompt=writer_system_prompt, 
                     max_output_tokens= 32200,
                     tools=[ "wikipedia_extract", "web_search2","write_tool"]
                    )
Writer_Agent = BaseAgent(config)


critic_system_prompt = """
You are an excellent article Reviewr. Your task is to review the article and provide meticulous feedback. Think of the reader's perspective and provide the useful crticism and areas of improvements.
Once everythin looks perfect output approved in the response and  write the article to the disk.
"""
config = CreateAgent(name="Critic_Agent", 
                     model_name="gemini/gemini-3.1-flash-lite", 
                     system_prompt=critic_system_prompt,
                     max_output_tokens= 32200 ,
                     tools=[ "write_tool"]
                    )
Critic_Agent = BaseAgent(config)

DAG = [Writer_Agent, Critic_Agent]
max_itteration = 2
iteration = 0

q = "Write an article about pros and cons of AI."


def single_llm_call(agent, max_try=1):
    for j in range(max_try):
        
        if len(agent.config.tools)>0:
            agent.set_tools_definations( [TOOL_REGISTRY[k] for k in agent.config.tools] )
        response = agent.run(completion)
        output = response.choices[0].message
        print(output)
        if output.tool_calls:
            # print(output.tool_calls)
            tool_call = output.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            print(function_args)

            function_response = TOOLS_to_FUNCTION[function_name](
                ** function_args
            )
            print(function_response)
            
            agent.add_tool_response(
                id =  tool_call.id,
                function_name = function_name,
                response = function_response,
            )

            

        else:
            return output.content
    
    
    return json.dumps({"status":"failure", "reason":"max try reached"})


        

session_history = []
while True and iteration<max_itteration:

    
    if iteration==0:
        Writer_Agent.add_message(
                "user",
                UserQuery(
                    query= q,
                    query_type= Query("text")
                )
            )
        
        writer_output = single_llm_call(Writer_Agent, 2)
    else:

        Writer_Agent.add_message(
            "user",
            query=UserQuery(
                query= f"{Critic_Agent.config.name}'s output: {critic_output}",
                query_type= Query("text")
                )
            )
        writer_output = single_llm_call(Writer_Agent, 2)

    session_history.append(writer_output)
    Critic_Agent.add_message(
        role = "user",
        query = UserQuery(
            query = f"{Writer_Agent.config.name}'s output: {writer_output}" , 
            query_type= Query("text")
        ) 
        
    )

    critic_output = single_llm_call(Critic_Agent)
    session_history.append(critic_output)

    if "approved" in critic_output.lower():
        break

    iteration += 1

print(session_history)

print(Writer_Agent.costs)
print(Critic_Agent.costs)




        