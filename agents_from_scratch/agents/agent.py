from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from uuid import uuid4
from datetime import datetime
from enum import StrEnum
import litellm
load_dotenv() 



class Query(StrEnum):
    TEXT = "text"
    IMAGE_URL = "image_url"

class UserQuery(BaseModel):
    query: str| List[str]
    query_type: Query | List[Query]


class AgentClientConfig(BaseModel):
    temperature: float = Field(default=0.2, ge=0, le=2)
    thinking:bool = Field(default=False)
    max_output_tokens:int = Field(default= 8126)
    max_thinking_tokens:int = Field(default=0)
    seed:int = Field(default=31122)

class AgentConfig(BaseModel):
    name: str 
    model_name: str
    system_prompt: str = Field(default="You are an helpful agent.")
    memory: Optional[str] = None #Field(default=None)
    tools: Optional[List[str]] = Field(default=[])

class CreateAgent(AgentConfig, AgentClientConfig):
    id: str = Field(default_factory=lambda: uuid4().hex)
    creation_timestamp:  datetime = Field(default_factory=datetime.now)

class UpdateAgent(AgentConfig, AgentClientConfig):
    id: str
    updation_timestamp: datetime = Field(default_factory=datetime.now)


class BaseAgent:

    def __init__(self, agent_config):
        self.config = agent_config

        self.history = []
        self.costs = {
            "input_cost": [],
            "output_cost": [],
        }
        self.tools = []
        self.tools_definations = []

        self.input_cost, self.output_cost = litellm.cost_per_token(model=self.config.model_name, completion_tokens=1000, prompt_tokens=1000  )


    def _add_message(self, query:str, query_type:Query):
        
        
        if query_type == Query.IMAGE_URL:
            return {
                "type" : query_type.value,
                query_type.value : {
                    "url" : f"data:image/jpeg;base64,{query}"
                }
            }
    
        else:
            return {
                "type" : query_type.value,
                query_type.value : query
            }
   
    
    def add_message(self, role:Literal["user", "assitant"], query:UserQuery):
       
        if len(self.history)==0:
            self.history.append(
                {
                    "role" : "system",
                    "content" : [
                            {
                                "type" : "text",
                                "text" : self.config.system_prompt
                            }
                    ]
                }
            )
        
        if type(query.query)!=list:
            result = self._add_message(query.query, query.query_type)
            self.history.append(
                {
                    "role": role,
                    "content":[
                        result
                ]
                }

            )
        else:

            self.history.append(
                {
                    "role": role,
                    "content":[ 
                       self._add_message(q, q_type)
                    for q, q_type in zip(query.query, query.query_type)
                ]
            }

            )



    

    def add_tool_response(self, id:str, function_name:str, response:str):
        self.history.append(
            {
                "role": "tool",
                "tool_call_id": id,
                "name": function_name,
                "content": response,
            }
        )

    def set_tools_definations(self, definations:List):
        self.tools_definations = definations

    def unset_tools_definations(self):
        self.tools_definations = []
    
    async def _run_async(self, completion, response_format=None):
        args = {
            "model" : self.config.model_name,
            "messages" : self.history,
            "temperature" : self.config.temperature,
            "max_completion_tokens": self.config.max_output_tokens,
        }

        if response_format is not None:
            args["response_format"] = response_format

        if len(self.config.tools)>0:
            args["tools"] = self.tools_definations
            args["tool_choice"] = "auto"
      
        response = await completion(**args)
        return response
        

    def _run(self, completion, response_format = None):
        args = {
            "model" : self.config.model_name,
            "messages" : self.history,
            "temperature" : self.config.temperature,
            "max_completion_tokens": self.config.max_output_tokens,
        }

        if response_format is not None:
            args["response_format"] = response_format

        if len(self.config.tools)>0:
            args["tools"] = self.tools_definations
            args["tool_choice"] = "auto"
      

        response = completion(**args)
        return response


    def run(self, completion, response_format=None, async_execute=False):
        try:
           
            if async_execute:
                response = self._run_async(completion, response_format)
            else:
                response = self._run(completion, response_format)
            
            # input_cost, output_cost= litellm.cost_per_token(model=self.config.model_name, completion_tokens=response.usage.completion_tokens, prompt_tokens=response.usage.prompt_tokens  )
            input_cost = (response.usage.prompt_tokens * self.input_cost) / 1000
            output_cost = (response.usage.completion_tokens * self.output_cost)/ 1000
            self.costs["input_cost"].append(input_cost)
            self.costs["output_cost"].append(output_cost)
            return response

        except Exception as e:
            print(f"An error occurred: {e}")


    
   
        
if __name__ == "__main__":
    from utils import encode_image
    from litellm import completion

    class ImageAnalysis(BaseModel):
        thinking: str
        description: str
        confidence_score: float
        key_elements: list[str]


    agent_config = CreateAgent(name="Agent1", model_name="gemini/gemini-2.5-flash", )
    agent = BaseAgent(agent_config)

    
    encoded_image = encode_image("D:/cursor project/math_tutor/backend/problem1.jpg")
    agent.add_message("user", UserQuery(query =[
            "Analyze this image and return the data strictly matching the provided schema.",
            encoded_image
         
        ],
        query_type=[
            Query("text"),
            Query("image_url")
        ]
        )
    )

    print(agent.config)

    response = agent.run(completion, ImageAnalysis)

    print(response.choices[0].message.content)
    print(agent.costs)