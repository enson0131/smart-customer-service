import { ChatOpenAI } from "@langchain/openai";
import { MODEL } from "../constants";

export interface Settings { DEEPSEEK_API_KEY:string; DEEPSEEK_BASE_URL?:string }
export function modelFor(env: Settings) {
  return new ChatOpenAI({apiKey:env.DEEPSEEK_API_KEY, model:MODEL, timeout:55000, maxRetries:1,
    configuration:{baseURL:env.DEEPSEEK_BASE_URL || "https://api.deepseek.com"},
    modelKwargs:{thinking:{type:"disabled"}}});
}
