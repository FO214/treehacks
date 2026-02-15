export interface PokeOptions {
    apiKey?: string;
    baseUrl?: string;
}
export interface SendMessageResponse {
    success: boolean;
    message: string;
}
export interface SendWebhookResponse {
    success: boolean;
}
export interface CreateWebhookResponse {
    triggerId: string;
    webhookUrl: string;
    webhookToken: string;
}
export declare class Poke {
    private apiKey;
    private baseUrl;
    constructor(options?: PokeOptions);
    private request;
    sendMessage(text: string): Promise<SendMessageResponse>;
    sendWebhook({ webhookUrl, webhookToken, data, }: {
        webhookUrl: string;
        webhookToken: string;
        data: Record<string, unknown>;
    }): Promise<SendWebhookResponse>;
    createWebhook({ condition, action, }: {
        condition: string;
        action: string;
    }): Promise<CreateWebhookResponse>;
}
