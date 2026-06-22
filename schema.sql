--
-- PostgreSQL database dump
--

\restrict IS0vbNQ9aaZeYJr9ajA7WvxiASNZkCzIa5zXxYQHwzM6TaqCegYkJRz2ro5sSpA

-- Dumped from database version 14.20 (Homebrew)
-- Dumped by pg_dump version 14.20 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: attachment_analysis; Type: TABLE; Schema: public; Owner: kinnu
--

CREATE TABLE public.attachment_analysis (
    id integer NOT NULL,
    attachment_id integer,
    ai_summary text,
    ai_extracted_text text,
    processed_at timestamp without time zone
);


ALTER TABLE public.attachment_analysis OWNER TO kinnu;

--
-- Name: attachment_analysis_id_seq; Type: SEQUENCE; Schema: public; Owner: kinnu
--

CREATE SEQUENCE public.attachment_analysis_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.attachment_analysis_id_seq OWNER TO kinnu;

--
-- Name: attachment_analysis_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kinnu
--

ALTER SEQUENCE public.attachment_analysis_id_seq OWNED BY public.attachment_analysis.id;


--
-- Name: attachments; Type: TABLE; Schema: public; Owner: kinnu
--

CREATE TABLE public.attachments (
    id integer NOT NULL,
    message_id text,
    filename character varying(255),
    file_type character varying(100),
    file_path text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    ai_summary text
);


ALTER TABLE public.attachments OWNER TO kinnu;

--
-- Name: attachments_id_seq; Type: SEQUENCE; Schema: public; Owner: kinnu
--

CREATE SEQUENCE public.attachments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.attachments_id_seq OWNER TO kinnu;

--
-- Name: attachments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kinnu
--

ALTER SEQUENCE public.attachments_id_seq OWNED BY public.attachments.id;


--
-- Name: conversation_messages; Type: TABLE; Schema: public; Owner: kinnu
--

CREATE TABLE public.conversation_messages (
    id integer NOT NULL,
    chat_id character varying(255),
    sender character varying(255),
    body text,
    created_at timestamp without time zone,
    source character varying(50) DEFAULT 'teacher_portal'::character varying,
    routing_status character varying(50),
    message_id character varying(255),
    ai_category character varying(50),
    ai_priority character varying(20),
    ai_summary text,
    ai_draft_reply text,
    ai_processed boolean DEFAULT false,
    ai_reply text,
    reply_sent boolean DEFAULT false,
    reply_sent_at timestamp without time zone
);


ALTER TABLE public.conversation_messages OWNER TO kinnu;

--
-- Name: conversation_messages_id_seq; Type: SEQUENCE; Schema: public; Owner: kinnu
--

CREATE SEQUENCE public.conversation_messages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.conversation_messages_id_seq OWNER TO kinnu;

--
-- Name: conversation_messages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kinnu
--

ALTER SEQUENCE public.conversation_messages_id_seq OWNED BY public.conversation_messages.id;


--
-- Name: conversations; Type: TABLE; Schema: public; Owner: kinnu
--

CREATE TABLE public.conversations (
    id integer NOT NULL,
    chat_id character varying(255),
    parent_name character varying(255),
    teacher_name character varying(255),
    updated_at timestamp without time zone,
    teacher_id character varying(255),
    parent_id character varying(255)
);


ALTER TABLE public.conversations OWNER TO kinnu;

--
-- Name: conversations_id_seq; Type: SEQUENCE; Schema: public; Owner: kinnu
--

CREATE SEQUENCE public.conversations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.conversations_id_seq OWNER TO kinnu;

--
-- Name: conversations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kinnu
--

ALTER SEQUENCE public.conversations_id_seq OWNED BY public.conversations.id;


--
-- Name: email_logs; Type: TABLE; Schema: public; Owner: kinnu
--

CREATE TABLE public.email_logs (
    id integer NOT NULL,
    message_id text,
    event_type character varying(50),
    details text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.email_logs OWNER TO kinnu;

--
-- Name: email_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: kinnu
--

CREATE SEQUENCE public.email_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.email_logs_id_seq OWNER TO kinnu;

--
-- Name: email_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kinnu
--

ALTER SEQUENCE public.email_logs_id_seq OWNED BY public.email_logs.id;


--
-- Name: messages; Type: TABLE; Schema: public; Owner: kinnu
--

CREATE TABLE public.messages (
    id integer NOT NULL,
    sender text,
    subject text,
    body text,
    category text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    status character varying(20) DEFAULT 'New'::character varying,
    message_id text,
    source character varying(50),
    contact_name character varying(255),
    phone character varying(50),
    priority character varying(20),
    ai_summary text,
    ai_draft_reply text,
    thread_id text,
    in_reply_to text,
    reply_sent boolean DEFAULT false,
    sent_at timestamp without time zone,
    sent_by character varying(20),
    resolved_at timestamp without time zone,
    first_reply_at timestamp without time zone,
    sent_message_id text
);


ALTER TABLE public.messages OWNER TO kinnu;

--
-- Name: messages_id_seq; Type: SEQUENCE; Schema: public; Owner: kinnu
--

CREATE SEQUENCE public.messages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.messages_id_seq OWNER TO kinnu;

--
-- Name: messages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kinnu
--

ALTER SEQUENCE public.messages_id_seq OWNED BY public.messages.id;


--
-- Name: attachment_analysis id; Type: DEFAULT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.attachment_analysis ALTER COLUMN id SET DEFAULT nextval('public.attachment_analysis_id_seq'::regclass);


--
-- Name: attachments id; Type: DEFAULT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.attachments ALTER COLUMN id SET DEFAULT nextval('public.attachments_id_seq'::regclass);


--
-- Name: conversation_messages id; Type: DEFAULT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.conversation_messages ALTER COLUMN id SET DEFAULT nextval('public.conversation_messages_id_seq'::regclass);


--
-- Name: conversations id; Type: DEFAULT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.conversations ALTER COLUMN id SET DEFAULT nextval('public.conversations_id_seq'::regclass);


--
-- Name: email_logs id; Type: DEFAULT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.email_logs ALTER COLUMN id SET DEFAULT nextval('public.email_logs_id_seq'::regclass);


--
-- Name: messages id; Type: DEFAULT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.messages ALTER COLUMN id SET DEFAULT nextval('public.messages_id_seq'::regclass);


--
-- Name: attachment_analysis attachment_analysis_pkey; Type: CONSTRAINT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.attachment_analysis
    ADD CONSTRAINT attachment_analysis_pkey PRIMARY KEY (id);


--
-- Name: attachments attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_pkey PRIMARY KEY (id);


--
-- Name: conversation_messages conversation_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.conversation_messages
    ADD CONSTRAINT conversation_messages_pkey PRIMARY KEY (id);


--
-- Name: conversations conversations_chat_id_key; Type: CONSTRAINT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_chat_id_key UNIQUE (chat_id);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: email_logs email_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.email_logs
    ADD CONSTRAINT email_logs_pkey PRIMARY KEY (id);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);


--
-- Name: conversation_messages unique_conversation_message_id; Type: CONSTRAINT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.conversation_messages
    ADD CONSTRAINT unique_conversation_message_id UNIQUE (message_id);


--
-- Name: messages unique_message_id; Type: CONSTRAINT; Schema: public; Owner: kinnu
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT unique_message_id UNIQUE (message_id);


--
-- PostgreSQL database dump complete
--

\unrestrict IS0vbNQ9aaZeYJr9ajA7WvxiASNZkCzIa5zXxYQHwzM6TaqCegYkJRz2ro5sSpA

